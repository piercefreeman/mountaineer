from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from json import dumps as json_dumps
from pathlib import Path
from shutil import rmtree as shutil_rmtree
from time import monotonic_ns
from typing import Any

from fastapi import APIRouter
from inflection import camelize
from pydantic_core import ValidationError

from mountaineer.actions import get_function_metadata
from mountaineer.actions.fields import FunctionActionType
from mountaineer.app import AppController, ControllerDefinition
from mountaineer.client_builder.build_actions import (
    OpenAPIToTypescriptActionConverter,
)
from mountaineer.client_builder.build_links import OpenAPIToTypescriptLinkConverter
from mountaineer.client_builder.build_schemas import OpenAPIToTypescriptSchemaConverter
from mountaineer.client_builder.openapi import (
    OpenAPIDefinition,
    OpenAPISchema,
    gather_all_models,
    resolve_ref,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)
from mountaineer.client_compiler.exceptions import BuildProcessException
from mountaineer.console import CONSOLE
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath, generate_relative_import
from mountaineer.static import get_static_path


@dataclass
class RenderSpec:
    url: str | None
    view_path: str
    spec: dict[Any, Any] | None


class ClientBuilder:
    """
    Main entrypoint for building the auto-generated typescript code. This includes
    the server provided API used by useServer.

    It delegates out the compilation to the js_compiler/* package.

    """

    def __init__(
        self,
        app: AppController,
        live_reload_port: int | None = None,
        build_cache: Path | None = None,
    ):
        self.openapi_schema_converter = OpenAPIToTypescriptSchemaConverter(
            export_interface=True
        )
        self.openapi_action_converter = OpenAPIToTypescriptActionConverter()
        self.openapi_link_converter = OpenAPIToTypescriptLinkConverter()

        self.app = app
        self.view_root = ManagedViewPath.from_view_root(app.view_root)
        self.live_reload_port = live_reload_port
        self.build_cache = build_cache

    async def build_all(self):
        # Totally clear away the old build cache, so we start fresh
        # and don't have additional files hanging around
        for clear_dir in [
            self.view_root.get_managed_ssr_dir(),
            self.view_root.get_managed_static_dir(),
        ]:
            if clear_dir.exists():
                shutil_rmtree(clear_dir)

        await self.build_use_server()
        # await self.build_fe_diff(None)

    async def build_use_server(self):
        start = monotonic_ns()

        # Avoid rebuilding if we don't need to
        if self.cache_is_outdated():
            with (
                self.catch_build_exception(),
                CONSOLE.status("Building useServer", spinner="dots"),
            ):
                # Make sure our application definitions are in a valid state before we start
                # to build the client code
                self.validate_unique_paths()

                # Static files that don't depend on client code
                self.generate_static_files()

                # The order of these generators don't particularly matter since most TSX linters
                # won't refresh until they're all complete. However, this ordering better aligns
                # with semantic dependencies so we keep the linearity where possible.
                self.generate_model_definitions()
                self.generate_action_definitions()
                self.generate_link_shortcuts()
                self.generate_link_aggregator()
                self.generate_view_servers()
                self.generate_index_file()
            CONSOLE.print(
                f"[bold green]🔨 Built useServer in {(monotonic_ns() - start) / 1e9:.2f}s"
            )
        else:
            CONSOLE.print(
                f"[bold green]Validated useServer in {(monotonic_ns() - start) / 1e9:.2f}s"
            )

    @contextmanager
    def catch_build_exception(self):
        try:
            yield
        except BuildProcessException as e:
            self.app.build_exception = e
            raise

    def generate_static_files(self):
        """
        Copy over the static files that are required for the client.

        """
        for static_filename in ["api.ts", "live_reload.ts"]:
            managed_code_dir = self.view_root.get_managed_code_dir()
            api_content = get_static_path(static_filename).read_text()
            (managed_code_dir / static_filename).write_text(api_content)

    def generate_model_definitions(self):
        """
        Generate the interface type definitions for the models. These most closely
        apply to the controller that they're defined within, so we create the files
        directly within the controller's view directory.

        """
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller

            schemas = self._generate_controller_schema(controller)

            # We put in one big models.ts file to enable potentially cyclical dependencies
            managed_code_dir = self.view_root.get_controller_view_path(
                controller
            ).get_managed_code_dir()
            (managed_code_dir / "models.ts").write_text(
                "\n\n".join(
                    [
                        schema
                        for _, schema in sorted(schemas.items(), key=lambda x: x[0])
                    ]
                )
            )

    def _generate_controller_schema(self, controller: ControllerBase):
        action_spec_openapi = self.openapi_action_specs[controller]

        try:
            action_base = OpenAPIDefinition(**action_spec_openapi)
        except ValidationError as e:
            LOGGER.error(
                f"Error parsing {controller} action spec: {action_spec_openapi} {e}"
            )
            raise e

        render_spec_openapi = self.openapi_render_specs[controller]
        render_base = (
            OpenAPISchema(**render_spec_openapi.spec)
            if render_spec_openapi.spec
            else None
        )

        schemas: dict[str, str] = {}

        # Convert the render model
        if render_base:
            for (
                schema_name,
                component,
            ) in self.openapi_schema_converter.convert_schema_to_typescript(
                render_base,
                # Render models are sent server -> client, so we know they'll provide all their
                # values in the initial payload
                all_fields_required=True,
            ).items():
                schemas[schema_name] = component

        # Convert all the other models defined in sideeffect routes
        # Iterate through all paths and their actions
        convert_models = defaultdict(set)
        for path, endpoint in action_base.paths.items():
            for action in endpoint.actions:
                # Request bodies support optional types
                if action.requestBody:
                    content_definition = action.requestBody.content_schema
                    if content_definition.schema_ref.ref:
                        all_models = gather_all_models(
                            action_base,
                            resolve_ref(content_definition.schema_ref.ref, action_base),
                        )
                        for model in all_models:
                            convert_models[model].add("request")

                # Response bodies will be fully hydrated from the server and therefore
                # will contain every value
                for status_code, response in action.responses.items():
                    content_definition = response.content_schema
                    if content_definition.schema_ref.ref:
                        all_models = gather_all_models(
                            action_base,
                            resolve_ref(content_definition.schema_ref.ref, action_base),
                        )
                        for model in all_models:
                            convert_models[model].add("response")

        for model, schema_types in convert_models.items():
            # If there are any request models, we should make them all optional
            # We'll have to do this until we have different models for request/response
            all_fields_required = all(
                schema_type == "response" for schema_type in schema_types
            )

            schemas[
                model.title
            ] = self.openapi_schema_converter.convert_schema_to_interface(
                model,
                base=action_base,
                # Don't require client data uploads to have all the fields
                # if there's a value specified server side. Note that this will apply
                # to both requests/response models right now, so clients might need
                # to do additional validation on the response side to confirm that
                # the server did send down the default values.
                # This is in contrast to the render() where we always know the response
                # payloads should be force required.
                all_fields_required=all_fields_required,
            )

        return schemas

    def generate_action_definitions(self):
        """
        Generate the actions for each controller. This should correspond the actions that are accessible
        via the OpenAPI schema and the internal router.

        """
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller
            controller_code_dir = self.view_root.get_controller_view_path(
                controller
            ).get_managed_code_dir()
            root_code_dir = self.view_root.get_managed_code_dir()

            controller_action_path = controller_code_dir / "actions.ts"
            root_common_handler = root_code_dir / "api.ts"
            root_api_import_path = generate_relative_import(
                controller_action_path, root_common_handler
            )

            openapi_raw = self.openapi_from_controller(controller_definition)
            output_schemas, required_types = self.openapi_action_converter.convert(
                openapi_raw
            )

            chunks: list[str] = []

            chunks.append(
                f"import {{ __request, FetchErrorBase }} from '{root_api_import_path}';\n"
                + f"import type {{ {', '.join(required_types)} }} from './models';"
            )

            chunks += output_schemas.values()

            controller_action_path.write_text("\n\n".join(chunks))

    def generate_link_shortcuts(self):
        """
        Generate the local link formatters that are tied to each controller.

        """
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller
            controller_code_dir = self.view_root.get_controller_view_path(
                controller
            ).get_managed_code_dir()
            root_code_dir = self.view_root.get_managed_code_dir()

            controller_links_path = controller_code_dir / "links.ts"

            root_common_handler = root_code_dir / "api.ts"
            root_api_import_path = generate_relative_import(
                controller_links_path, root_common_handler
            )
            render_route = controller_definition.render_router

            # This controller isn't accessible via a URL so shouldn't have a
            # link associated with it
            # This file still needs to exist for downstream exports so we write
            # a blank file
            if render_route is None:
                controller_links_path.write_text("")
                continue

            render_openapi = self.app.generate_openapi(
                routes=render_route.routes,
            )

            content = ""
            content += f"import {{ __getLink }} from '{root_api_import_path}';\n"
            content += self.openapi_link_converter.convert(render_openapi)

            controller_links_path.write_text(content)

    def generate_link_aggregator(self):
        """
        We need a global function that references each controller's link generator,
        so we can do controller->global->controller.

        """
        global_code_dir = self.view_root.get_managed_code_dir()

        import_paths: list[str] = []
        global_setters: dict[str, str] = {}

        # For each controller, import the links and export them
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller

            # Layout controllers don't have links, so the import path won't be
            # able to find a valid file reference
            if isinstance(controller, LayoutControllerBase):
                continue

            controller_code_dir = self.view_root.get_controller_view_path(
                controller
            ).get_managed_code_dir()

            relative_import = generate_relative_import(
                global_code_dir / "links.ts",
                controller_code_dir / "links.ts",
            )

            # Avoid global namespace collisions
            local_link_function_name = (
                f"{camelize(controller.__class__.__name__)}GetLinks"
            )

            import_paths.append(
                f"import {{ getLink as {local_link_function_name} }} from '{relative_import}';"
            )
            global_setters[
                TSLiteral(camelize(controller.__class__.__name__, False))
            ] = TSLiteral(local_link_function_name)

        lines = [
            *import_paths,
            f"const linkGenerator = {python_payload_to_typescript(global_setters)};\n",
            "export default linkGenerator;",
        ]

        (global_code_dir / "links.ts").write_text("\n".join(lines))

    def generate_view_servers(self):
        """
        Generate the useServer() hooks within each local view. These will reference the main
        server provider and allow each view to access the particular server state that
        is linked to that controller.

        """
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller
            controller_key = controller.__class__.__name__

            chunks: list[str] = []

            # Step 1: Interface to optionally override the current controller state
            # We want to have an inline reference to a model which is compatible with the base render model alongside
            # all sideeffect sub-models. Since we're re-declaring this in the server file, we also
            # have to bring with us all of the other sub-model imports.
            render_model_name = self.get_render_local_state(controller)

            # Step 2: Find the actions that are relevant
            controller_action_metadata = [
                metadata for _, _, metadata in controller._get_client_functions()
            ]

            # Step 2: Setup imports from the single global provider
            controller_model_path = self.view_root.get_controller_view_path(
                controller
            ).get_managed_code_dir()
            global_server_path = self.view_root.get_managed_code_dir()
            relative_server_path = generate_relative_import(
                controller_model_path, global_server_path
            )

            chunks.append(
                "import React, { useState } from 'react';\n"
                + f"import {{ applySideEffect }} from '{relative_server_path}/api';\n"
                + f"import LinkGenerator from '{relative_server_path}/links';\n"
                + f"import {{ {render_model_name} }} from './models';\n"
                + (
                    f"import {{ {', '.join([metadata.function_name for metadata in controller_action_metadata])} }} from './actions';"
                    if controller_action_metadata
                    else ""
                )
            )

            # Step 3: Add the optional model definition - this allows any controller that returns a partial
            # side-effect to update the full model with the same typehint
            optional_model_name = f"{render_model_name}Optional"
            chunks.append(
                f"export type {optional_model_name} = Partial<{render_model_name}>;"
            )

            # Step 4: We expect another script has already injected this global `SERVER_DATA` constant. We
            # add the typehinting here just so that the IDE can be happy.
            chunks.append("declare global {\n" "var SERVER_DATA: any;\n" "}\n")

            # Step 5: Typehint the return type of the server state in case client callers
            # want to pass this to sub-functions
            chunks.append(
                f"export interface ServerState extends {render_model_name} {{\n"
                + "linkGenerator: typeof LinkGenerator;\n"
                + (
                    "\n".join(
                        [
                            f"{metadata.function_name}: typeof {metadata.function_name};"
                            for metadata in controller_action_metadata
                        ]
                    )
                    if controller_action_metadata
                    else ""
                )
                + "}\n"
            )

            # Step 6: Final implementation of the useServer() hook, which returns a subview of the overall
            # server state that's only relevant to this controller
            chunks.append(
                "export const useServer = () : ServerState => {\n"
                + f"const [ serverState, setServerState ] = useState(SERVER_DATA['{controller_key}'] as {render_model_name});\n"
                # Local function to just override the current controller
                # We make sure to wait for the previous state to be set, in case of a
                # differential update
                + f"const setControllerState = (payload: {optional_model_name}) => {{\n"
                + "setServerState((state) => ({\n"
                + "...state,\n"
                + "...payload,\n"
                + "}));\n"
                + "};\n"
                + "return {\n"
                + "...serverState,\n"
                + "linkGenerator: LinkGenerator,\n"
                + ",\n".join(
                    [
                        (
                            f"{metadata.function_name}: applySideEffect({metadata.function_name}, setControllerState)"
                            if metadata.action_type == FunctionActionType.SIDEEFFECT
                            else f"{metadata.function_name}: {metadata.function_name}"
                        )
                        for metadata in controller_action_metadata
                    ]
                )
                + "}\n"
                + "};"
            )

            (controller_model_path / "useServer.ts").write_text("\n\n".join(chunks))

    def generate_index_file(self):
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller
            controller_code_dir = self.view_root.get_controller_view_path(
                controller
            ).get_managed_code_dir()

            chunks: list[str] = []

            # Depending on our build pipeline, some of these files might not exist
            # or be empty (no module exports). We want to make sure that we don't
            # try to re-export empty values or Typescript will fail to compile
            # with error TS2306: File 'myfile.ts' is not a module.
            export_paths = ["actions", "links", "models", "useServer"]
            for export_path in export_paths:
                file = controller_code_dir / f"{export_path}.ts"
                if file.exists() and file.read_text().strip():
                    chunks.append(f"export * from './{export_path}';")

            (controller_code_dir / "index.ts").write_text("\n".join(chunks))

    def cache_is_outdated(self):
        """
        Determines if our last build is outdated and we need to rebuild the client. Running
        this function will also update the cache to the current state.

        """
        # We need to rebuild every time
        if not self.build_cache:
            return True

        start = monotonic_ns()

        cached_metadata = self.build_cache / "client_builder_openapi.json"
        cached_contents = {
            controller_definition.controller.__class__.__name__: {
                "action": self.openapi_action_specs[controller_definition.controller],
                "render": asdict(
                    self.openapi_render_specs[controller_definition.controller]
                ),
            }
            for controller_definition in self.app.controllers
        }

        cached_str = json_dumps(cached_contents, sort_keys=True)
        LOGGER.debug(f"Cache check took {(monotonic_ns() - start) / 1e9}s")

        if not cached_metadata.exists():
            cached_metadata.write_text(cached_str)
            return True

        if cached_metadata.read_text() != cached_str:
            cached_metadata.write_text(cached_str)
            return True

        return False

    def validate_unique_paths(self):
        """
        Validate that all controller paths are unique. Otherwise we risk stomping
        on other server metadata that has already been written.

        """
        # Validation 1: Ensure that all view paths are unique
        # This applies to both exact equivalence (two controllers pointing to the
        # same page.tsx) as well as conflicting folder structures (one controller pointing
        # to a page and another pointing to a layout in the same directory).
        # Both of these causes would cause conflicting _server files to be generated
        # which we need to avoid
        view_counts = defaultdict(list)
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller
            view_counts[
                self.view_root.get_controller_view_path(controller).parent
            ].append(controller)
        duplicate_views = [
            (view, controllers)
            for view, controllers in view_counts.items()
            if len(controllers) > 1
        ]

        if duplicate_views:
            raise ValueError(
                "Found duplicate view paths under controller management, ensure definitions are unique",
                "\n".join(
                    f"  {view}: {controller}"
                    for view, controllers in duplicate_views
                    for controller in controllers
                ),
            )

        # Validation 2: Ensure that the paths actually exist
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller
            view_path = self.view_root.get_controller_view_path(controller)
            if not view_path.exists():
                raise ValueError(
                    f"View path {view_path} does not exist, ensure it is created before running the server"
                )

    def get_render_local_state(self, controller: ControllerBase):
        """
        Returns the local type name for the render model. Scoped for use
        within the controller's view directory.

        :returns ReturnModel
        """
        render_metadata = get_function_metadata(controller.render)
        render_model = render_metadata.get_render_model()

        if not render_model:
            raise ValueError(
                f"Controller {controller} does not have a render model defined"
            )

        return camelize(render_model.__name__)

    def openapi_from_controller(self, controller_definition: ControllerDefinition):
        """
        Small hack to get the full path to the root of the server. By default the controller just
        has the path relative to the controller API.

        """
        root_router = APIRouter()
        root_router.include_router(
            controller_definition.router, prefix=controller_definition.url_prefix
        )
        return self.app.generate_openapi(routes=root_router.routes)

    @property
    def openapi_action_specs(self):
        """
        Cache the OpenAPI specs for all side-effects. Render components
        are defined differently. We internally cache this for all stages that require it.

        """
        if not hasattr(self, "_openapi_action_specs"):
            self._openapi_action_specs: dict[ControllerBase, dict[Any, Any]] = {}

            for controller_definition in self.app.controllers:
                controller = controller_definition.controller
                self._openapi_action_specs[controller] = self.openapi_from_controller(
                    controller_definition
                )

        return self._openapi_action_specs

    @property
    def openapi_render_specs(self):
        """
        Get the raw spec for all the render attributes.

        If the return model for a render function is "None", the response spec will
        include {controller: {spec: None}} be so clients can separate undefined controllers from
        defined controllers with no return model.

        """
        if not hasattr(self, "_openapi_render_specs"):
            self._openapi_render_specs: dict[ControllerBase, RenderSpec] = {}

            for controller_definition in self.app.controllers:
                controller = controller_definition.controller

                render_metadata = get_function_metadata(controller.render)
                render_model = render_metadata.get_render_model()

                spec = (
                    self.openapi_schema_converter.get_model_json_schema(render_model)
                    if render_model
                    else None
                )
                self._openapi_render_specs[controller] = RenderSpec(
                    url=None
                    if isinstance(controller, LayoutControllerBase)
                    else controller.url,
                    view_path=str(controller.view_path),
                    spec=spec,
                )

        return self._openapi_render_specs
