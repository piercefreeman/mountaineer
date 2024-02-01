import asyncio
from collections import defaultdict
from hashlib import md5
from pathlib import Path
from shutil import rmtree

from fastapi import APIRouter
from fastapi.openapi.utils import get_openapi
from inflection import camelize, underscore

from filzl.actions import get_function_metadata
from filzl.actions.fields import FunctionActionType
from filzl.app import AppController, ControllerDefinition
from filzl.client_builder.bundler import JavascriptBundler
from filzl.client_builder.esbuild import ESBuildWrapper
from filzl.client_interface.build_actions import (
    OpenAPIToTypescriptActionConverter,
)
from filzl.client_interface.build_links import OpenAPIToTypescriptLinkConverter
from filzl.client_interface.build_schemas import OpenAPIToTypescriptSchemaConverter
from filzl.client_interface.openapi import OpenAPIDefinition
from filzl.client_interface.paths import generate_relative_import
from filzl.client_interface.source_maps import (
    get_cleaned_js_contents,
    update_source_map_path,
)
from filzl.client_interface.typescript import TSLiteral, python_payload_to_typescript
from filzl.controller import ControllerBase
from filzl.static import get_static_path


class ClientBuilder:
    """
    Main entrypoint for building the auto-generated typescript code.

    """

    def __init__(self, app: AppController):
        self.openapi_schema_converter = OpenAPIToTypescriptSchemaConverter(
            export_interface=True
        )
        self.openapi_action_converter = OpenAPIToTypescriptActionConverter()
        self.openapi_link_converter = OpenAPIToTypescriptLinkConverter()

        self.app = app
        self.view_root = app.view_root

    def build(self):
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

        self.build_javascript_chunks()

    def generate_static_files(self):
        """
        Copy over the static files that are required for the client.

        """
        managed_code_dir = self.get_managed_code_dir(self.view_root)
        api_content = get_static_path("api.ts").read_text()
        (managed_code_dir / "api.ts").write_text(api_content)

    def generate_model_definitions(self):
        """
        Generate the interface type definitions for the models. These most closely
        apply to the controller that they're defined within, so we create the files
        directly within the controller's view directory.

        """
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller

            openapi_spec = self.openapi_from_controller(controller_definition)
            base = OpenAPIDefinition(**openapi_spec)

            schemas: dict[str, str] = {}

            # Convert the render model
            render_metadata = get_function_metadata(controller.render)
            for schema_name, component in self.openapi_schema_converter.convert(
                render_metadata.get_render_model()
            ).items():
                schemas[schema_name] = component

            # Convert the sideeffect routes
            for schema_name, component in base.components.schemas.items():
                schemas[
                    schema_name
                ] = self.openapi_schema_converter.convert_schema_to_interface(
                    component,
                    base=base,
                )

            # We put in one big models.ts file to enable potentially cyclical dependencies
            managed_code_dir = self.get_managed_code_dir(
                self.get_controller_view_path(controller)
            )
            (managed_code_dir / "models.ts").write_text(
                "\n\n".join(
                    [
                        schema
                        for _, schema in sorted(schemas.items(), key=lambda x: x[0])
                    ]
                )
            )

    def generate_action_definitions(self):
        """
        Generate the actions for each controller. This should correspond the actions that are accessible
        via the OpenAPI schema and the internal router.

        """
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller
            controller_code_dir = self.get_managed_code_dir(
                self.get_controller_view_path(controller)
            )
            root_code_dir = self.get_managed_code_dir(self.view_root)

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
            controller_code_dir = self.get_managed_code_dir(
                self.get_controller_view_path(controller)
            )
            root_code_dir = self.get_managed_code_dir(self.view_root)

            controller_links_path = controller_code_dir / "links.ts"

            root_common_handler = root_code_dir / "api.ts"
            root_api_import_path = generate_relative_import(
                controller_links_path, root_common_handler
            )
            render_route = get_function_metadata(controller.render).get_render_router()
            render_openapi = get_openapi(
                title="",
                version="",
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
        global_code_dir = self.get_managed_code_dir(self.view_root)

        import_paths: list[str] = []
        global_setters: dict[str, str] = {}

        # For each controller, import the links and export them
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller
            controller_code_dir = self.get_managed_code_dir(
                self.get_controller_view_path(controller)
            )

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
            controller_model_path = self.get_managed_code_dir(
                self.get_controller_view_path(controller)
            )
            global_server_path = self.get_managed_code_dir(self.view_root)
            relative_server_path = generate_relative_import(
                controller_model_path, global_server_path
            )

            chunks.append(
                "import React, { useState } from 'react';\n"
                + f"import {{ applySideEffect }} from '{relative_server_path}/api';\n"
                + f"import LinkGenerator from '{relative_server_path}/links';\n"
                + f"import {{ {render_model_name} }} from './models';"
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

            # Step 5: Final implementation of the useServer() hook, which returns a subview of the overall
            # server state that's only relevant to this controller
            chunks.append(
                "export const useServer = () => {\n"
                + f"const [ serverState, setServerState ] = useState(SERVER_DATA as {render_model_name});\n"
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

    def build_javascript_chunks(self):
        """
        Build the final javascript chunks that will render the react documents. Each page will get
        one chunk associated with it. We suffix these files with the current md5 hash of the contents to
        allow clients to aggressively cache these contents but invalidate the cache whenever the script
        contents have rebuilt in the background.

        """
        # Clear the static directories since we only want the latest files in there
        static_dir = self.get_managed_static_dir(self.view_root)
        ssr_dir = self.get_managed_ssr_dir(self.view_root)
        for clear_dir in [static_dir, ssr_dir]:
            if clear_dir.exists():
                rmtree(clear_dir)
            clear_dir.mkdir(parents=True)

        # Before we spawn our different processes, we make sure that we can actually resolve
        # the esbuild path. We want one exception / download flow, not one per process.
        esbuilder = ESBuildWrapper()
        if not esbuilder.get_esbuild_path():
            raise ValueError("Unable to resolve esbuild path")

        async def spawn_builder(controller: ControllerBase):
            # TODO: If we get to many hundred or thousand of view files, we might want to introduce a work
            # queue to avoid spawning too many processes concurrently
            bundler = JavascriptBundler(
                self.get_controller_view_path(controller), self.view_root
            )
            bundle_definition = await bundler.convert()

            # Client-side scripts have to be provided a cache-invalidation suffix alongside
            # mapping the source map to the new script name
            controller_base = underscore(controller.__class__.__name__)
            content_hash = md5(
                get_cleaned_js_contents(
                    bundle_definition.client_compiled_contents
                ).encode()
            ).hexdigest()
            script_name = f"{controller_base}-{content_hash}.js"
            map_name = f"{script_name}.map"

            # Map to the new script name
            contents = update_source_map_path(
                bundle_definition.client_compiled_contents, map_name
            )

            (static_dir / script_name).write_text(contents)
            (static_dir / map_name).write_text(
                bundle_definition.client_source_map_contents
            )

            ssr_path = ssr_dir / f"{controller_base}.js"
            ssr_path.write_text(bundle_definition.server_compiled_contents)

        async def parallel_build():
            tasks = [
                spawn_builder(controller_definition.controller)
                for controller_definition in self.app.controllers
            ]
            await asyncio.gather(*tasks)

        # Each build command is completely independent and there's some overhead with spawning
        # each process. Make use of multi-core machines and spawn each process in its own
        # management thread so we complete the build process in parallel.
        asyncio.run(parallel_build())

    def get_managed_code_dir(self, path: Path):
        return self.get_managed_dir_common(path, "_server")

    def get_managed_static_dir(self, path: Path):
        return self.get_managed_dir_common(path, "_static")

    def get_managed_ssr_dir(self, path: Path):
        return self.get_managed_dir_common(path, "_ssr")

    def get_managed_dir_common(self, path: Path, managed_dir: str):
        # If the path is to a file, we want to get the parent directory
        # so that we can create the managed code directory
        # We also create the managed code directory if it doesn't exist so all subsequent
        # calls can immediately start writing to it
        if path.is_file():
            path = path.parent
        managed_code_dir = path / managed_dir
        managed_code_dir.mkdir(exist_ok=True)
        return managed_code_dir

    def validate_unique_paths(self):
        """
        Validate that all controller paths are unique. Otherwise we risk stomping
        on other server metadata that has already been written.

        """
        # Validation 1: Ensure that all view paths are unique
        view_counts = defaultdict(list)
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller
            view_counts[self.get_controller_view_path(controller).parent].append(
                controller
            )
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
            view_path = self.get_controller_view_path(controller)
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
        return camelize(render_metadata.get_render_model().__name__)

    def openapi_from_controller(self, controller_definition: ControllerDefinition):
        """
        Small hack to get the full path to the root of the server. By default the controller just
        has the path relative to the controller API.

        """
        root_router = APIRouter()
        root_router.include_router(
            controller_definition.router, prefix=controller_definition.url_prefix
        )
        return get_openapi(title="", version="", routes=root_router.routes)

    def get_controller_view_path(self, controller: ControllerBase):
        """
        Assume all paths are specified in terms of their relative root
        """
        relative_path = Path(controller.view_path.lstrip("/"))
        return self.app.view_root / relative_path
