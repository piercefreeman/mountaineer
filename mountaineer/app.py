from functools import wraps
from inspect import isclass, signature
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from inflection import underscore
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from starlette.routing import BaseRoute

from mountaineer.actions import (
    FunctionActionType,
    fuse_metadata_to_response_typehint,
    init_function_metadata,
)
from mountaineer.annotation_helpers import MountaineerUnsetValue
from mountaineer.controller import ControllerBase
from mountaineer.exceptions import APIException, APIExceptionInternalModelBase
from mountaineer.js_compiler.base import ClientBuilderBase
from mountaineer.js_compiler.bundler import JavascriptBundler
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath
from mountaineer.render import Metadata


class ControllerDefinition(BaseModel):
    controller: ControllerBase
    router: APIRouter
    # URL prefix to the root of the server
    url_prefix: str
    # Dynamically generated function that actually renders the html content
    # This is a hybrid between render() and _generate_html()
    view_route: Callable

    model_config = {
        "arbitrary_types_allowed": True,
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
        view_root: Path,
        global_metadata: Metadata | None = None,
        custom_builders: list[ClientBuilderBase] | None = None,
        config: BaseSettings | None = None,
    ):
        """
        :param global_metadata: Script and meta will be applied to every
            page rendered by this application. Title will only be applied
            if the page does not already have a title set.
        :param config: Application global configuration.

        """
        self.app = FastAPI(title=name, version=version)
        self.controllers: list[ControllerDefinition] = []
        self.name = name
        self.version = version
        self.view_root = ManagedViewPath.from_view_root(view_root)
        self.global_metadata = global_metadata
        self.builders = [
            # Default builders
            JavascriptBundler(),
            # Custom builders
            *(custom_builders if custom_builders else []),
        ]

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

        """
        # Update the paths now that we have access to the runtime package path
        controller.resolve_paths(self.view_root)

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
            or (isclass(return_model) and issubclass(return_model, BaseModel))
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
        render_metadata.render_router = view_router
        self.app.include_router(view_router)

        # Create a wrapper router for each controller to hold the side-effects
        controller_api = APIRouter()
        controller_url_prefix = (
            f"{self.internal_api_prefix}/{underscore(controller.__class__.__name__)}"
        )
        for _, fn, metadata in controller._get_client_functions():
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

            metadata.url = (
                f"{controller_url_prefix}/{metadata.function_name.strip('/')}"
            )

            controller_api.post(f"/{metadata.function_name}")(fn)

        # Originally we tried implementing a sub-router for the internal API that was registered in the __init__
        # But the application greedily copies all contents from the router when it's added via `include_router`, so this
        # resulted in our endpoints not being seen even after calls to `.register(). We therefore attach the new
        # controller router directly to the application, since this will trigger a new copy of the routes.
        self.app.include_router(
            controller_api,
            prefix=controller_url_prefix,
        )

        LOGGER.debug(f"Did register controller: {controller.__class__.__name__}")

        self.controllers.append(
            ControllerDefinition(
                controller=controller,
                router=controller_api,
                view_route=generate_controller_html,
                url_prefix=controller_url_prefix,
            )
        )

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

        # Loop over the registered controllers and get the actions
        exceptions_by_url = {}
        for controller_definition in self.controllers:
            for (
                _,
                _,
                metadata,
            ) in controller_definition.controller._get_client_functions():
                exceptions_models = metadata.get_exception_models()
                if not exceptions_models:
                    continue
                exceptions_by_url[metadata.url] = [
                    (
                        model.status_code,
                        model.InternalModel.__name__,
                        model.InternalModel.model_json_schema(),
                    )
                    for model in exceptions_models
                ]

        # Add to the schemas dictionary first
        # TODO: Add validation that throws an error on duplicate names
        # TODO: Add validation that throws an error for duplicate error codes
        for url, exception_payloads in exceptions_by_url.items():
            # Not included in the specified routes, we should ignore this controller
            if url not in openapi_base["paths"]:
                continue

            for status_code, schema_name, schema in exception_payloads:
                other_definitions = {
                    definition_name: self._update_ref_path(definition)
                    for definition_name, definition in schema.pop("$defs", {}).items()
                }
                openapi_base["components"]["schemas"].update(other_definitions)
                openapi_base["components"]["schemas"][
                    schema_name
                ] = self._update_ref_path(schema)

                # All actions are "posts" by definition
                openapi_base["paths"][url]["post"]["responses"][str(status_code)] = {
                    "description": f"Custom Error: {schema_name}",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{schema_name}"}
                        }
                    },
                }

        return openapi_base

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
