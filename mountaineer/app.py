from collections import defaultdict
from functools import wraps
from inspect import isclass, signature
from pathlib import Path
from typing import Any, Callable, Type

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from inflection import underscore
from pydantic import BaseModel
from starlette.routing import BaseRoute

from mountaineer.actions import (
    FunctionActionType,
    fuse_metadata_to_response_typehint,
    init_function_metadata,
)
from mountaineer.actions.fields import FunctionMetadata
from mountaineer.annotation_helpers import MountaineerUnsetValue
from mountaineer.config import ConfigBase
from mountaineer.controller import ControllerBase
from mountaineer.exceptions import APIException, APIExceptionInternalModelBase
from mountaineer.js_compiler.base import ClientBuilderBase
from mountaineer.js_compiler.javascript import JavascriptBundler
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath, resolve_package_path
from mountaineer.render import Metadata, RenderBase


class ControllerDefinition(BaseModel):
    controller: ControllerBase
    router: APIRouter
    # URL prefix to the root of the server
    url_prefix: str
    # Dynamically generated function that actually renders the html content
    # This is a hybrid between render() and _generate_html()
    view_route: Callable
    render_router: APIRouter

    model_config = {
        "arbitrary_types_allowed": True,
    }

    def get_url_for_metadata(self, metadata: FunctionMetadata):
        return f"{self.url_prefix}/{metadata.function_name.strip('/')}"


class ExceptionSchema(BaseModel):
    status_code: int
    schema_name: str
    schema_name_long: str
    schema_value: dict[str, Any]

    model_config = {
        "extra": "forbid",
    }


class AppController:
    """
    Main entrypoint of a project web application.

    """

    builders: list[ClientBuilderBase]
    global_metadata: Metadata | None

    def __init__(
        self,
        *,
        name: str = "Mountaineer Webapp",
        version: str = "0.1.0",
        view_root: Path | None = None,
        global_metadata: Metadata | None = None,
        custom_builders: list[ClientBuilderBase] | None = None,
        config: ConfigBase | None = None,
        fastapi_args: dict[str, Any] | None = None,
    ):
        """
        :param global_metadata: Script and meta will be applied to every
            page rendered by this application. Title will only be applied
            if the page does not already have a title set.
        :param config: Application global configuration.

        """
        self.app = FastAPI(title=name, version=version, **(fastapi_args or {}))
        self.controllers: list[ControllerDefinition] = []
        self.controller_names: set[str] = set()
        self.name = name
        self.version = version
        self.global_metadata = global_metadata
        self.builders = [
            # Default builders
            JavascriptBundler(
                environment=(
                    config.ENVIRONMENT if config is not None else "development"
                )
            ),
            # Custom builders
            *(custom_builders if custom_builders else []),
        ]

        # If this flag is present, we will re-raise this error during render()
        # so users can see the error in the browser.
        # This is useful for debugging, but should not be used in production
        self.build_exception: Exception | None = None

        # Follow our managed path conventions
        if config is not None and config.PACKAGE is not None:
            package_path = resolve_package_path(config.PACKAGE)
            self.view_root = ManagedViewPath.from_view_root(package_path / "views")
        elif view_root is not None:
            self.view_root = ManagedViewPath.from_view_root(view_root)
        else:
            raise ValueError(
                "You must provide either a config.package or a view_root to the AppController"
            )

        # The act of instantiating the config should register it with the
        # global settings registry. We keep a reference to it so we can shortcut
        # to the user-defined settings later, but this is largely optional.
        self.config = config

        self.internal_api_prefix = "/internal/api"

        # The static directory has to exist before we try to mount it
        static_dir = self.view_root.get_managed_static_dir()

        # Mount the view_root / _static directory, since we'll need
        # this for the client mounted view files
        self.app.mount(
            "/static",
            StaticFiles(directory=str(static_dir)),
            name="static",
        )

        self.app.exception_handler(APIException)(self.handle_exception)

        self.app.openapi = self.generate_openapi  # type: ignore

    def register(self, controller: ControllerBase):
        """
        Register a new controller. This will:

        - Mount the html of the controller to the main application service
        - Mount all actions (ie. @sideeffect and @passthrough decorated functions) to their public API

        :param controller: The controller instance that should be added to your webapp. The class accepts a full
        instance instead of just a class, so you're able to perform any kind of runtime initialization of the
        kwarg args that you need before it's registered.

        """
        # Since the controller name is used to build dependent files, we ensure
        # that we only register one controller of a given name
        controller_name = controller.__class__.__name__
        if controller_name in self.controller_names:
            raise ValueError(
                f"Controller with name {controller_name} already registered."
            )

        # Update the paths now that we have access to the runtime package path
        controller.resolve_paths(self.view_root, force=True)

        # The controller superclass needs to be initialized before it's
        # registered into the application
        if not hasattr(controller, "initialized"):
            raise ValueError(
                f"You must call super().__init__() on {controller} before it can be registered."
            )

        # We need to passthrough the API of the render function to the FastAPI router so it's called properly
        # with the dependency injection kwargs
        @wraps(controller.render)
        async def generate_controller_html(*args, **kwargs):
            if self.build_exception:
                raise self.build_exception

            try:
                return await controller._generate_html(
                    *args, global_metadata=self.global_metadata, **kwargs
                )
            except Exception as e:
                # If a user explicitly is raising an APIException, we don't want to log it
                if not isinstance(e, (APIExceptionInternalModelBase, HTTPException)):
                    # Forward along the exception, just modify it to include
                    # the controller name for additional context
                    LOGGER.error(
                        f"Exception encountered in {controller.__class__.__name__} rendering"
                    )
                raise

        # Strip the return annotations from the function, since we just intend to return an HTML page
        # and not a JSON response
        if not hasattr(generate_controller_html, "__wrapped__"):
            raise ValueError(
                "Unable to clear wrapped typehint, no wrapped function found."
            )

        return_model = generate_controller_html.__wrapped__.__annotations__.get(
            "return", MountaineerUnsetValue()
        )
        if isinstance(return_model, MountaineerUnsetValue):
            raise ValueError(
                "Controller render() function must have a return type annotation"
            )

        # Only the signature of the actual rendering function, not the original. We might
        # need to sniff render() again for its typehint
        generate_controller_html.__signature__ = signature(  # type: ignore
            generate_controller_html,
        ).replace(return_annotation=None)

        # Validate the return model is actually a RenderBase or explicitly marked up as None
        if not (
            return_model is None
            or (isclass(return_model) and issubclass(return_model, RenderBase))
        ):
            raise ValueError(
                "Controller render() return type annotation is not a RenderBase"
            )

        # Attach a new metadata wrapper to the original function so we can easily
        # recover it when attached to the class
        render_metadata = init_function_metadata(
            controller.render, FunctionActionType.RENDER
        )
        render_metadata.render_model = return_model

        # Register the rendering view to an isolated APIRoute, so we can keep track of its
        # the resulting router independently of the rest of the application
        # This is useful in cases where we need to do a render()->FastAPI lookup
        view_router = APIRouter()
        view_router.get(controller.url)(generate_controller_html)
        self.app.include_router(view_router)

        # Create a wrapper router for each controller to hold the side-effects
        controller_api = APIRouter()
        controller_url_prefix = (
            f"{self.internal_api_prefix}/{underscore(controller.__class__.__name__)}"
        )
        for _, fn, metadata in controller._get_client_functions():
            openapi_extra: dict[str, Any] = {
                "is_raw_response": metadata.get_is_raw_response()
            }

            if not metadata.get_is_raw_response():
                # We need to delay adding the typehint for each function until we are here, adding the view. Since
                # decorators run before the class is actually mounted, they're isolated from the larger class/controller
                # context that the action function is being defined within. Here since we have a global view
                # of the controller (render function + actions) this becomes trivial
                metadata.return_model = fuse_metadata_to_response_typehint(
                    metadata, render_metadata.get_render_model()
                )

                # Update the signature of the internal function, which fastapi will sniff for the return declaration
                # https://github.com/tiangolo/fastapi/blob/a235d93002b925b0d2d7aa650b7ab6d7bb4b24dd/fastapi/dependencies/utils.py#L207
                method_function: Callable = fn.__func__  # type: ignore
                method_function.__signature__ = signature(method_function).replace(  # type: ignore
                    return_annotation=metadata.return_model
                )

                # Pass along relevant tags in the OpenAPI meta struct
                # This will appear in the root key of the API route, at the same level of "summary" and "parameters"
                if metadata.get_media_type():
                    openapi_extra["media_type"] = metadata.get_media_type()

            controller_api.post(
                f"/{metadata.function_name}", openapi_extra=openapi_extra
            )(fn)

        # Originally we tried implementing a sub-router for the internal API that was registered in the __init__
        # But the application greedily copies all contents from the router when it's added via `include_router`, so this
        # resulted in our endpoints not being seen even after calls to `.register(). We therefore attach the new
        # controller router directly to the application, since this will trigger a new copy of the routes.
        self.app.include_router(
            controller_api,
            prefix=controller_url_prefix,
        )

        LOGGER.debug(f"Did register controller: {controller_name}")

        controller_definition = ControllerDefinition(
            controller=controller,
            router=controller_api,
            view_route=generate_controller_html,
            url_prefix=controller_url_prefix,
            render_router=view_router,
        )
        controller.definition = controller_definition

        self.controllers.append(controller_definition)
        self.controller_names.add(controller_name)

    async def handle_exception(self, request: Request, exc: APIException):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.internal_model.model_dump(),
        )

    def generate_openapi(self, routes: list[BaseRoute] | None = None):
        """
        Bundle custom user exceptions in the OpenAPI schema. By default
        endpoints just include the 422 Validation Error, but this allows
        for custom derived user methods.

        """
        openapi_base = get_openapi(
            title=self.name,
            version=self.version,
            routes=(routes if routes is not None else self.app.routes),
        )

        #
        # Exception injection
        #

        # Loop over the registered controllers and get the action exceptions
        exceptions_by_url: dict[str, list[ExceptionSchema]] = {}
        for controller_definition in self.controllers:
            for (
                _,
                _,
                metadata,
            ) in controller_definition.controller._get_client_functions():
                url = controller_definition.get_url_for_metadata(metadata)
                # Not included in the specified routes, we should ignore this controller
                if url not in openapi_base["paths"]:
                    continue

                exceptions_models = metadata.get_exception_models()
                if not exceptions_models:
                    continue

                exceptions_by_url[url] = [
                    self._format_exception_model(exception_model)
                    for exception_model in exceptions_models
                ]

        # Users are allowed to reference the same schema name multiple times so long
        # as they have the same value. If they use conflicting values we'll have
        # to use the long name instead of the short module name to avoid conflicting
        # schema definitions.
        schema_names_to_long: defaultdict[str, set[str]] = defaultdict(set)
        for exception_payloads in exceptions_by_url.values():
            for payload in exception_payloads:
                schema_names_to_long[payload.schema_name].add(payload.schema_name_long)

        duplicate_schema_names = {
            schema_name
            for schema_name, schema_name_longs in schema_names_to_long.items()
            if len(schema_name_longs) > 1
        }

        for url, exception_payloads in exceptions_by_url.items():
            existing_status_codes: set[int] = set()

            for payload in exception_payloads:
                # Validate the exception state doesn't override existing values
                # Status codes are local to this particular endpoint but schema names
                # are global because they're placed in the global components section
                if payload.status_code in existing_status_codes:
                    raise ValueError(
                        f"Duplicate status code {payload.status_code} for {url}"
                    )

                schema_name = (
                    payload.schema_name
                    if payload.schema_name not in duplicate_schema_names
                    else payload.schema_name_long
                )

                other_definitions = {
                    definition_name: self._update_ref_path(definition)
                    for definition_name, definition in payload.schema_value.pop(
                        "$defs", {}
                    ).items()
                }
                openapi_base["components"]["schemas"].update(other_definitions)
                openapi_base["components"]["schemas"][
                    schema_name
                ] = self._update_ref_path(payload.schema_value)

                # All actions are "posts" by definition
                openapi_base["paths"][url]["post"]["responses"][
                    str(payload.status_code)
                ] = {
                    "description": f"Custom Error: {payload.schema_name}",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{schema_name}"}
                        }
                    },
                }

                existing_status_codes.add(payload.status_code)

        return openapi_base

    def _format_exception_model(self, model: Type[APIException]) -> ExceptionSchema:
        # By default all fields are optional. Since we are sending them
        # from the server we are guaranteed they will either be explicitly
        # provided or fallback to their defaults
        json_schema = model.InternalModel.model_json_schema()
        json_schema["required"] = list(json_schema["properties"].keys())

        return ExceptionSchema(
            status_code=model.status_code,
            schema_name=model.InternalModel.__name__,
            schema_name_long=f"{model.InternalModel.__module__}.{model.InternalModel.__name__}",
            schema_value=json_schema,
        )

    def _update_ref_path(self, schema: Any):
        """
        The $ref values that come out of the model schema are tied to #/defs instead
        of the #/components/schemas. This function updates the schema to use the
        correct prefix for the final OpenAPI schema.

        """
        if isinstance(schema, dict):
            new_schema: dict[str, Any] = {}
            for key, value in schema.items():
                if key == "$ref":
                    schema_name = value.split("/")[-1]
                    new_schema[key] = f"#/components/schemas/{schema_name}"
                    continue
                elif key == "additionalProperties":
                    # If the value is "False", we need to remove the key
                    if value is False:
                        continue

                new_schema[key] = self._update_ref_path(value)
            return new_schema
        elif isinstance(schema, list):
            return [self._update_ref_path(value) for value in schema]
        else:
            return schema

    def definition_for_controller(
        self, controller: ControllerBase
    ) -> ControllerDefinition:
        for controller_definition in self.controllers:
            if controller_definition.controller == controller:
                return controller_definition
        raise ValueError(f"Controller {controller} not found")
