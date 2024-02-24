import asyncio
from collections import defaultdict
from inspect import isawaitable
from shutil import rmtree

from click import secho
from fastapi import APIRouter
from inflection import camelize

from mountaineer.actions import get_function_metadata
from mountaineer.actions.fields import FunctionActionType
from mountaineer.app import AppController, ControllerDefinition
from mountaineer.client_builder.build_actions import (
    OpenAPIToTypescriptActionConverter,
)
from mountaineer.client_builder.build_links import OpenAPIToTypescriptLinkConverter
from mountaineer.client_builder.build_schemas import OpenAPIToTypescriptSchemaConverter
from mountaineer.client_builder.openapi import OpenAPIDefinition
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)
from mountaineer.controller import ControllerBase
from mountaineer.io import gather_with_concurrency
from mountaineer.js_compiler.base import ClientBundleMetadata
from mountaineer.js_compiler.esbuild import ESBuildWrapper
from mountaineer.js_compiler.exceptions import BuildProcessException
from mountaineer.paths import ManagedViewPath, generate_relative_import
from mountaineer.static import get_static_path


class ClientBuilder:
    """
    Main entrypoint for building the auto-generated typescript code.

    """

    def __init__(self, app: AppController, live_reload_port: int | None = None):
        self.openapi_schema_converter = OpenAPIToTypescriptSchemaConverter(
            export_interface=True
        )
        self.openapi_action_converter = OpenAPIToTypescriptActionConverter()
        self.openapi_link_converter = OpenAPIToTypescriptLinkConverter()

        self.app = app
        self.view_root = ManagedViewPath.from_view_root(app.view_root)
        self.live_reload_port = live_reload_port

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

        # Update the cached paths attached to the app
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller
            controller.resolve_paths(self.view_root)

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
            render_route = get_function_metadata(controller.render).get_render_router()
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

    def build_javascript_chunks(self, max_concurrency: int = 25):
        """
        Build the final javascript chunks that will render the react documents. Each page will get
        one chunk associated with it. We suffix these files with the current md5 hash of the contents to
        allow clients to aggressively cache these contents but invalidate the cache whenever the script
        contents have rebuilt in the background.

        """
        # Clear the static directories since we only want the latest files in there
        static_dir = self.view_root.get_managed_static_dir()
        ssr_dir = self.view_root.get_managed_ssr_dir()
        for clear_dir in [static_dir, ssr_dir]:
            if clear_dir.exists():
                rmtree(clear_dir)
            clear_dir.mkdir(parents=True)

        # Before we spawn our different processes, we make sure that we can actually resolve
        # the esbuild path. We want one exception / download flow, not one per process.
        esbuilder = ESBuildWrapper()
        if not esbuilder.get_esbuild_path():
            raise ValueError("Unable to resolve esbuild path")

        metadata = ClientBundleMetadata(
            live_reload_port=self.live_reload_port,
        )

        async def spawn_builder(controller: ControllerBase):
            for builder in self.app.builders:
                result = builder.handle_file(
                    self.view_root.get_controller_view_path(controller),
                    controller,
                    metadata=metadata,
                )
                if isawaitable(result):
                    await result

        async def spawn_file_builder(path: ManagedViewPath):
            """
            Spawn non-controller based file builder
            """
            ignore_directories = ["_ssr", "_static", "_server", "node_modules"]
            # If any of these directories are in the path, we skip it
            if any([directory in path.parts for directory in ignore_directories]):
                return

            # Otherwise loop over our bundlers
            for builder in self.app.builders:
                result = builder.handle_file(path, controller=None, metadata=metadata)
                if isawaitable(result):
                    await result

        async def parallel_build():
            tasks = [
                spawn_builder(controller_definition.controller)
                for controller_definition in self.app.controllers
            ] + [
                # Optionally build static files the main views and plugin views
                # This allows plugins to have custom handling for different file types
                spawn_file_builder(path)
                for view_root in self.get_all_root_views()
                for path in view_root.rglob("*")
            ]
            results = await gather_with_concurrency(
                tasks, n=max_concurrency, catch_exceptions=True
            )

            # Go through the exceptions, logging the build errors explicitly
            has_build_error = False
            for result in results:
                if isinstance(result, Exception):
                    has_build_error = True
                    if isinstance(result, BuildProcessException):
                        secho(f"Build error: {result}", fg="red")
                    else:
                        raise result

            if has_build_error:
                raise BuildProcessException(
                    "Build process failed. Errors are listed in the console."
                )

        # Each build command is completely independent and there's some overhead with spawning
        # each process. Make use of multi-core machines and spawn each process in its own
        # management thread so we complete the build process in parallel.
        asyncio.run(parallel_build())

    def validate_unique_paths(self):
        """
        Validate that all controller paths are unique. Otherwise we risk stomping
        on other server metadata that has already been written.

        """
        # Validation 1: Ensure that all view paths are unique
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

    def get_all_root_views(self) -> list[ManagedViewPath]:
        """
        The self.view_root variable is the root of the current user project. We may have other
        "view roots" that store view for plugins.

        This function inspects the controller path definitions and collects all of the
        unique root view paths. The returned ManagedViewPaths are all copied and set to
        share the same package root as the user project.

        """
        # Find the view roots
        view_roots = {self.view_root.copy()}
        for controller_definition in self.app.controllers:
            view_path = controller_definition.controller.view_path
            if isinstance(view_path, ManagedViewPath):
                view_roots.add(view_path.get_root_link().copy())

        # All the view roots should have the same package root
        for view_root in view_roots:
            view_root.package_root_link = self.view_root.package_root_link

        return list(view_roots)

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
        return self.app.generate_openapi(routes=root_router.routes)
