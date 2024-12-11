from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from inspect import isfunction
from json import dumps as json_dumps
from pathlib import Path
from shutil import rmtree as shutil_rmtree
from time import monotonic_ns
from typing import Any, Type

from fastapi import APIRouter
from inflection import camelize
from pydantic_core import ValidationError

from mountaineer.actions import get_function_metadata
from mountaineer.actions.fields import FunctionActionType
from mountaineer.app import AppController, ControllerDefinition
from mountaineer.client_builder.build_actions import (
    OpenAPIToTypescriptActionConverter,
    TypescriptAction,
)
from mountaineer.controller import get_client_functions_cls
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
    normalize_interface
)
from graphlib import TopologicalSorter
from mountaineer.client_compiler.exceptions import BuildProcessException
from mountaineer.console import CONSOLE
from mountaineer.controller import ControllerBase, function_is_action
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath, generate_relative_import
from mountaineer.static import get_static_path
from mountaineer.render import RenderBase, RenderNull
from typing import TypeVar
from mountaineer.client_builder.parser import ControllerParser



T = TypeVar('T', bound=type)



@dataclass
class RenderSpec:
    url: str | None
    view_path: str
    spec: dict[Any, Any] | None


class APIBuilder:
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

        self.live_reload_port = live_reload_port
        self.build_cache = build_cache

        self._openapi_action_specs: dict[str, dict[Any, Any]] | None = None
        self._openapi_render_specs: dict[str, RenderSpec] | None = None

        self.update_controller(app)

    def update_controller(self, controller: AppController):
        self.app = controller
        self.view_root = ManagedViewPath.from_view_root(controller._view_root)
        self._openapi_action_specs = None
        self._openapi_render_specs = None

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
        parser = ControllerParser()

        for controller in self.app.controllers:
            parser.parse_controller(controller.controller)

#     async def build_use_server(self):
#         start = monotonic_ns()

#         # Avoid rebuilding if we don't need to
#         if self.cache_is_outdated():
#             with (
#                 self.catch_build_exception(),
#                 CONSOLE.status("Building useServer", spinner="dots"),
#             ):
#                 # Make sure our application definitions are in a valid state before we start
#                 # to build the client code
#                 self.validate_unique_paths()

#                 # Static files that don't depend on client code
#                 self.generate_static_files()

#                 # Centralized interface definitions that controllers have to conform to
#                 controller_definitions = self.generate_controller_definitions()

#                 # The order of these generators don't particularly matter since most TSX linters
#                 # won't refresh until they're all complete. However, this ordering better aligns
#                 # with semantic dependencies so we keep the linearity where possible.
#                 self.generate_model_definitions(controller_definitions)
#                 self.generate_action_definitions()
#                 self.generate_link_shortcuts()
#                 self.generate_link_aggregator()
#                 self.generate_view_servers()
#                 self.generate_index_file()
#             CONSOLE.print(
#                 f"[bold green]🔨 Built useServer in {(monotonic_ns() - start) / 1e9:.2f}s"
#             )
#         else:
#             CONSOLE.print(
#                 f"[bold green]Validated useServer in {(monotonic_ns() - start) / 1e9:.2f}s"
#             )

#     def generate_controller_definitions(self):
#         """
#         Generate centralized controller definitions with smart namespace resolution.
#         """
#         all_controllers_raw: set[Type[ControllerBase]] = set()
#         all_renders_raw: set[Type[RenderBase]] = set()
#         render_to_controller: dict[Type[ControllerBase], Type[RenderBase]] = {}
#         controller_to_subclasses: dict[Type[ControllerBase], list[ControllerBase]] = defaultdict(list)

#         # First pass: collect all classes
#         for controller_definition in self.app.controllers:
#             controller = controller_definition.controller
#             superclass_controllers = self._get_superclass_controllers(controller)

#             # Register all controllers with namespace resolver
#             self.namespace_resolver.register_class(controller.__class__)
#             for superclass in superclass_controllers:
#                 self.namespace_resolver.register_class(superclass)

#             all_controllers_raw.add(controller.__class__)
#             all_controllers_raw.update(superclass_controllers)

#             render_model = get_function_metadata(controller.render).get_render_model()
#             if render_model:
#                 # Register render models with namespace resolver
#                 self.namespace_resolver.register_class(render_model)
#                 all_renders_raw.add(render_model)
#                 for superclass in render_model.__mro__:
#                     if issubclass(superclass, RenderBase):
#                         self.namespace_resolver.register_class(superclass)
#                         all_renders_raw.add(superclass)
#                 render_to_controller[render_model] = controller.__class__

#             for superclass in superclass_controllers:
#                 controller_to_subclasses[superclass].append(controller.__class__)

#         # Resolve all namespaces after registration
#         self.namespace_resolver.resolve()

#         # Remove base classes
#         all_controllers_raw.discard(ControllerBase)
#         all_controllers_raw.discard(LayoutControllerBase)
#         all_renders_raw.discard(RenderBase)
#         all_renders_raw.discard(RenderNull)

#         # Sort classes by dependency
#         all_controllers = self.sort_classes_by_dependency(all_controllers_raw)
#         all_renders = self.sort_classes_by_dependency(all_renders_raw)

#         schemas: dict[str, str] = {}
#         dependencies_by_controller = defaultdict(list)

#         for controller in all_controllers:
#             controller_id = self.namespace_resolver.get_identifier(controller)

#             # Create synthetic APIRouter for controller actions
#             controller_api = APIRouter()
#             found_actions = list(get_client_functions_cls(controller))

#             for name, func, metadata in found_actions:
#                 controller_api.post(f"/{metadata.function_name}", openapi_extra=metadata.get_openapi_extras())(func)

#             openapi_raw = self.app.generate_openapi(routes=controller_api.routes)
#             openapi_spec = OpenAPIDefinition(**openapi_raw)

#             # Generate required models
#             convert_models = defaultdict(set)
#             for path, endpoint in openapi_spec.paths.items():
#                 for action in endpoint.actions:
#                     model_schemas: list[tuple[ContentDefinition, str]] = []

#                     if action.requestBody:
#                         content_definition = action.requestBody.content_schema
#                         model_schemas.append((content_definition, "request"))

#                     for status_code, response in action.responses.items():
#                         content_definition = response.content_schema
#                         model_schemas.append((content_definition, "response"))

#                     for content_definition, tag in model_schemas:
#                         if not content_definition.schema_ref.ref:
#                             continue
#                         all_models = gather_all_models(
#                             openapi_spec,
#                             resolve_ref(content_definition.schema_ref.ref, openapi_spec),
#                         )
#                         for model in all_models:
#                             convert_models[model].add(tag)

#             for model, schema_types in convert_models.items():
#                 all_fields_required = all(
#                     schema_type == "response" for schema_type in schema_types
#                 )

#                 interface = self.openapi_schema_converter.convert_schema_to_interface(
#                     model,
#                     base=openapi_spec,
#                     all_fields_required=all_fields_required,
#                 )

#                 schemas[model.title] = interface.to_js()

#                 for subclass in controller_to_subclasses[controller]:
#                     dependencies_by_controller[self.namespace_resolver.get_identifier(subclass)].append(interface)

#             # Generate interface for actions
#             action_definitions, error_definitions = self.openapi_action_converter.convert(
#                 openapi_raw
#             )
#             controller_definition = {}
#             for action_definition in action_definitions:
#                 controller_definition[TSLiteral(action_definition.name)] = TSLiteral(
#                     f"(params{'?' if action_definition.default_parameters else ''}: {action_definition.typehints}) => {action_definition.response_type}"
#                 )

#             superclass_names = ", ".join(
#                 self.namespace_resolver.get_typescript_name(superclass)
#                 for superclass in controller.__mro__
#                 if superclass in all_controllers and superclass != controller
#             )

#             typescript_name = self.namespace_resolver.get_typescript_name(controller)
#             schemas[controller_id] = (
#                 f"export interface {typescript_name} "
#                 + (f"extends {superclass_names}" if superclass_names else "")
#                 + f"{python_payload_to_typescript(controller_definition)}\n"
#             )

#         for render in all_renders:
#             # Get unique identifier for the render class
#             render_id = self.namespace_resolver.get_identifier(render)

#             spec = self.openapi_schema_converter.get_unique_subclass_json_schema(render)
#             render_base = OpenAPISchema(**spec)
#             owned_by_controller = render_to_controller.get(render)

#             # Convert the render model. This results in a one-to-many creation of schemas since
#             # we also have to bring in all the sub-models that are referenced in the render model
#             converted_schemas = self.openapi_schema_converter.convert_schema_to_typescript(
#                 render_base,
#                 # Render models are sent server -> client, so we know they'll provide all their
#                 # values in the initial payload
#                 all_fields_required=True,
#             )

#             # TODO: This isn't partitioning based on duplicate class names
#             for schema_name, component in converted_schemas.items():
#                 if schema_name == render.__name__:
#                     # Get superclass names using namespace resolution
#                     component.include_superclasses = [
#                         self.namespace_resolver.get_typescript_name(superclass)
#                         for superclass in render.__mro__
#                         if superclass in all_renders and superclass != render
#                     ]

#                 # Use namespace-aware schema name if this is the main render class
#                 final_schema_name = (
#                     self.namespace_resolver.get_typescript_name(render)
#                     if schema_name == render.__name__
#                     else schema_name
#                 )
#                 schemas[final_schema_name] = component.to_js()

#                 if owned_by_controller:
#                     controller_id = self.namespace_resolver.get_identifier(owned_by_controller)
#                     dependencies_by_controller[controller_id].append(component)

#         # Write schemas to file
#         global_code_dir = self.view_root.get_managed_code_dir()
#         (global_code_dir / "controllers.ts").write_text(
#             "\n\n".join(schemas.values())
#         )

#         return dependencies_by_controller

#     def generate_static_files(self):
#         """
#         Copy over the static files that are required for the client.

#         """
#         for static_filename in ["api.ts", "live_reload.ts"]:
#             managed_code_dir = self.view_root.get_managed_code_dir()
#             api_content = get_static_path(static_filename).read_text()
#             (managed_code_dir / static_filename).write_text(api_content)

#     def generate_model_definitions(self, controller_dependencies):
#         """
#         Generate the interface type definitions for the models. These most closely
#         apply to the controller that they're defined within, so we create the files
#         directly within the controller's view directory.

#         """
#         # Get the root path

#         for controller_definition in self.app.controllers:
#             controller = controller_definition.controller

#             controller_code_dir = self.view_root.get_controller_view_path(
#                 controller
#             ).get_managed_code_dir()
#             root_code_dir = self.view_root.get_managed_code_dir()

#             controller_action_path = controller_code_dir / "models.ts"
#             root_common_handler = root_code_dir / "controllers.ts"
#             root_api_import_path = generate_relative_import(
#                 controller_action_path, root_common_handler
#             )

#             # Determine all the models that are tied to this controller
#             contents = ""
#             contents += f"export type {{ {normalize_interface(controller.__class__.__name__)} }} from '{root_api_import_path}';\n"

#             already_exported: set[str] = set()
#             for value in controller_dependencies[controller.__class__.__name__]:
#                 if value.name in already_exported:
#                     continue
#                 export_type = "export type" if value.interface_type == "interface" else "export"
#                 contents += f"{export_type} {{ {normalize_interface(value.name)} }} from '{root_api_import_path}';\n"
#                 already_exported.add(value.name)

#             controller_action_path.write_text(contents)

#     def generate_action_definitions(self):
#         """
#         Generate the actions for each controller. This should correspond the actions that are accessible
#         via the OpenAPI schema and the internal router.

#         """
#         for controller_definition in self.app.controllers:
#             controller = controller_definition.controller
#             controller_code_dir = self.view_root.get_controller_view_path(
#                 controller
#             ).get_managed_code_dir()
#             root_code_dir = self.view_root.get_managed_code_dir()

#             controller_action_path = controller_code_dir / "actions.ts"
#             root_common_handler = root_code_dir / "api.ts"
#             root_api_import_path = generate_relative_import(
#                 controller_action_path, root_common_handler
#             )

#             # We can't use the given definitions for now because we need to take the fully qualified
#             # path from the actual controller instantiation versus our synthetic controller
#             # from the class definition
#             openapi_raw = self.openapi_from_controller(controller_definition)
#             actions, errors = self.openapi_action_converter.convert(
#                 openapi_raw
#             )
#             required_types = {normalize_interface(model) for action in actions for model in action.required_models}
#             required_types |= {normalize_interface(model) for error in errors for model in error.required_models}

#             chunks: list[str] = []

#             chunks.append(
#                 f"import {{ __request, FetchErrorBase }} from '{root_api_import_path}';\n"
#                 + (f"import type {{ {', '.join(required_types)} }} from './models';\n" if required_types else "")
#             )

#             for action in actions:
#                 chunks.append(action.to_js() + "\n")

#             seen_errors : set[str] = set()
#             for error in errors:
#                 if error.name in seen_errors:
#                     continue
#                 chunks.append(error.to_js() + "\n")
#                 seen_errors.add(error.name)

#             controller_action_path.write_text("\n\n".join(chunks))

#     def generate_link_shortcuts(self):
#         """
#         Generate the local link formatters that are tied to each controller.

#         """
#         for controller_definition in self.app.controllers:
#             controller = controller_definition.controller
#             controller_code_dir = self.view_root.get_controller_view_path(
#                 controller
#             ).get_managed_code_dir()
#             root_code_dir = self.view_root.get_managed_code_dir()

#             controller_links_path = controller_code_dir / "links.ts"

#             root_common_handler = root_code_dir / "api.ts"
#             root_api_import_path = generate_relative_import(
#                 controller_links_path, root_common_handler
#             )
#             render_route = controller_definition.render_router

#             # This controller isn't accessible via a URL so shouldn't have a
#             # link associated with it
#             # This file still needs to exist for downstream exports so we write
#             # a blank file
#             if render_route is None:
#                 controller_links_path.write_text("")
#                 continue

#             render_openapi = self.app.generate_openapi(
#                 routes=render_route.routes,
#             )

#             content = ""
#             content += f"import {{ __getLink }} from '{root_api_import_path}';\n"
#             content += self.openapi_link_converter.convert(render_openapi)

#             controller_links_path.write_text(content)

#     def generate_link_aggregator(self):
#         """
#         We need a global function that references each controller's link generator,
#         so we can do controller->global->controller.

#         """
#         global_code_dir = self.view_root.get_managed_code_dir()

#         import_paths: list[str] = []
#         global_setters: dict[str, str] = {}

#         # For each controller, import the links and export them
#         for controller_definition in self.app.controllers:
#             controller = controller_definition.controller

#             # Layout controllers don't have links, so the import path won't be
#             # able to find a valid file reference
#             if isinstance(controller, LayoutControllerBase):
#                 continue

#             controller_code_dir = self.view_root.get_controller_view_path(
#                 controller
#             ).get_managed_code_dir()

#             relative_import = generate_relative_import(
#                 global_code_dir / "links.ts",
#                 controller_code_dir / "links.ts",
#             )

#             # Avoid global namespace collisions
#             local_link_function_name = (
#                 f"{camelize(controller.__class__.__name__)}GetLinks"
#             )

#             import_paths.append(
#                 f"import {{ getLink as {local_link_function_name} }} from '{relative_import}';"
#             )
#             global_setters[
#                 TSLiteral(camelize(controller.__class__.__name__, False))
#             ] = TSLiteral(local_link_function_name)

#         lines = [
#             *import_paths,
#             f"const linkGenerator = {python_payload_to_typescript(global_setters)};\n",
#             "export default linkGenerator;",
#         ]

#         (global_code_dir / "links.ts").write_text("\n".join(lines))

#     def generate_view_servers(self):
#         """
#         Generate the useServer() hooks within each local view. These will reference the main
#         server provider and allow each view to access the particular server state that
#         is linked to that controller.

#         """
#         for controller_definition in self.app.controllers:
#             controller = controller_definition.controller
#             controller_key = controller.__class__.__name__

#             chunks: list[str] = []

#             # Step 1: Interface to optionally override the current controller state
#             # We want to have an inline reference to a model which is compatible with the base render model alongside
#             # all sideeffect sub-models. Since we're re-declaring this in the server file, we also
#             # have to bring with us all of the other sub-model imports.
#             render_model_name = self.get_render_local_state(controller)

#             # Step 2: Find the actions that are relevant
#             controller_action_metadata = [
#                 metadata for _, _, metadata in controller._get_client_functions()
#             ]

#             # Step 2: Setup imports from the single global provider
#             controller_model_path = self.view_root.get_controller_view_path(
#                 controller
#             ).get_managed_code_dir()
#             global_server_path = self.view_root.get_managed_code_dir()
#             relative_server_path = generate_relative_import(
#                 controller_model_path, global_server_path
#             )

#             chunks.append(
#                 "import React, { useState } from 'react';\n"
#                 + f"import {{ applySideEffect }} from '{relative_server_path}/api';\n"
#                 + f"import LinkGenerator from '{relative_server_path}/links';\n"
#                 + f"import {{ {render_model_name}, {controller_key} }} from './models';\n"
#                 + (
#                     f"import {{ {', '.join([metadata.function_name for metadata in controller_action_metadata])} }} from './actions';"
#                     if controller_action_metadata
#                     else ""
#                 )
#             )

#             # Step 3: Add the optional model definition - this allows any controller that returns a partial
#             # side-effect to update the full model with the same typehint
#             optional_model_name = f"{render_model_name}Optional"
#             chunks.append(
#                 f"export type {optional_model_name} = Partial<{render_model_name}>;"
#             )

#             # Step 4: We expect another script has already injected this global `SERVER_DATA` constant. We
#             # add the typehinting here just so that the IDE can be happy.
#             chunks.append("declare global {\n" "var SERVER_DATA: any;\n" "}\n")

#             # Step 5: Typehint the return type of the server state in case client callers
#             # want to pass this to sub-functions
#             chunks.append(
#                 f"export interface ServerState extends {render_model_name}, {controller_key} {{\n"
#                 + "linkGenerator: typeof LinkGenerator;\n"
#                 + "}\n"
#             )

#             # Step 6: Final implementation of the useServer() hook, which returns a subview of the overall
#             # server state that's only relevant to this controller
#             chunks.append(
#                 "export const useServer = () : ServerState => {\n"
#                 + f"const [ serverState, setServerState ] = useState(SERVER_DATA['{controller_key}'] as {render_model_name});\n"
#                 # Local function to just override the current controller
#                 # We make sure to wait for the previous state to be set, in case of a
#                 # differential update
#                 + f"const setControllerState = (payload: {optional_model_name}) => {{\n"
#                 + "setServerState((state) => ({\n"
#                 + "...state,\n"
#                 + "...payload,\n"
#                 + "}));\n"
#                 + "};\n"
#                 + "return {\n"
#                 + "...serverState,\n"
#                 + "linkGenerator: LinkGenerator,\n"
#                 + ",\n".join(
#                     [
#                         (
#                             f"{metadata.function_name}: applySideEffect({metadata.function_name}, setControllerState)"
#                             if metadata.action_type == FunctionActionType.SIDEEFFECT
#                             else f"{metadata.function_name}: {metadata.function_name}"
#                         )
#                         for metadata in controller_action_metadata
#                     ]
#                 )
#                 + "}\n"
#                 + "};"
#             )

#             (controller_model_path / "useServer.ts").write_text("\n\n".join(chunks))

#     def generate_index_file(self):
#         for controller_definition in self.app.controllers:
#             controller = controller_definition.controller
#             controller_code_dir = self.view_root.get_controller_view_path(
#                 controller
#             ).get_managed_code_dir()

#             chunks: list[str] = []

#             # Depending on our build pipeline, some of these files might not exist
#             # or be empty (no module exports). We want to make sure that we don't
#             # try to re-export empty values or Typescript will fail to compile
#             # with error TS2306: File 'myfile.ts' is not a module.
#             export_paths = ["actions", "links", "models", "useServer"]
#             for export_path in export_paths:
#                 file = controller_code_dir / f"{export_path}.ts"
#                 if file.exists() and file.read_text().strip():
#                     chunks.append(f"export * from './{export_path}';")

#             (controller_code_dir / "index.ts").write_text("\n".join(chunks))

#     def cache_is_outdated(self):
#         """
#         Determines if our last build is outdated and we need to rebuild the client. Running
#         this function will also update the cache to the current state.

#         """
#         # We need to rebuild every time
#         if not self.build_cache:
#             return True

#         start = monotonic_ns()

#         cached_metadata = self.build_cache / "client_builder_openapi.json"
#         cached_contents = {
#             controller_definition.controller.__class__.__name__: {
#                 "action": self.openapi_action_specs[
#                     controller_definition.controller.__class__.__name__
#                 ],
#                 "render": asdict(
#                     self.openapi_render_specs[
#                         controller_definition.controller.__class__.__name__
#                     ]
#                 ),
#             }
#             for controller_definition in self.app.controllers
#         }

#         cached_str = json_dumps(cached_contents, sort_keys=True)
#         LOGGER.debug(f"Cache check took {(monotonic_ns() - start) / 1e9}s")

#         if not cached_metadata.exists():
#             cached_metadata.write_text(cached_str)
#             return True

#         if cached_metadata.read_text() != cached_str:
#             cached_metadata.write_text(cached_str)
#             return True

#         return False

#     def validate_unique_paths(self):
#         """
#         Validate that all controller paths are unique. Otherwise we risk stomping
#         on other server metadata that has already been written.

#         """
#         # Validation 1: Ensure that all view paths are unique
#         # This applies to both exact equivalence (two controllers pointing to the
#         # same page.tsx) as well as conflicting folder structures (one controller pointing
#         # to a page and another pointing to a layout in the same directory).
#         # Both of these causes would cause conflicting _server files to be generated
#         # which we need to avoid
#         view_counts = defaultdict(list)
#         for controller_definition in self.app.controllers:
#             controller = controller_definition.controller
#             view_counts[
#                 self.view_root.get_controller_view_path(controller).parent
#             ].append(controller)
#         duplicate_views = [
#             (view, controllers)
#             for view, controllers in view_counts.items()
#             if len(controllers) > 1
#         ]

#         if duplicate_views:
#             raise ValueError(
#                 "Found duplicate view paths under controller management, ensure definitions are unique",
#                 "\n".join(
#                     f"  {view}: {controller}"
#                     for view, controllers in duplicate_views
#                     for controller in controllers
#                 ),
#             )

#         # Validation 2: Ensure that the paths actually exist
#         for controller_definition in self.app.controllers:
#             controller = controller_definition.controller
#             view_path = self.view_root.get_controller_view_path(controller)
#             if not view_path.exists():
#                 raise ValueError(
#                     f"View path {view_path} does not exist, ensure it is created before running the server"
#                 )

#     def get_render_local_state(self, controller: ControllerBase):
#         """
#         Returns the local type name for the render model. Scoped for use
#         within the controller's view directory.

#         :returns ReturnModel
#         """
#         render_metadata = get_function_metadata(controller.render)
#         render_model = render_metadata.get_render_model()

#         if not render_model:
#             raise ValueError(
#                 f"Controller {controller} does not have a render model defined"
#             )

#         return camelize(render_model.__name__)

#     def openapi_from_controller(self, controller_definition: ControllerDefinition):
#         """
#         Small hack to get the full path to the root of the server. By default the controller just
#         has the path relative to the controller API.

#         """
#         root_router = APIRouter()
#         root_router.include_router(
#             controller_definition.router, prefix=controller_definition.url_prefix
#         )
#         return self.app.generate_openapi(routes=root_router.routes)

#     @property
#     def openapi_action_specs(self):
#         """
#         Cache the OpenAPI specs for all side-effects. Render components
#         are defined differently. We internally cache this for all stages that require it.

#         """
#         if self._openapi_action_specs is None:
#             self._openapi_action_specs = {}

#             for controller_definition in self.app.controllers:
#                 controller = controller_definition.controller
#                 self._openapi_action_specs[
#                     controller.__class__.__name__
#                 ] = self.openapi_from_controller(controller_definition)

#         return self._openapi_action_specs

#     @property
#     def openapi_render_specs(self):
#         """
#         Get the raw spec for all the render attributes.

#         If the return model for a render function is "None", the response spec will
#         include {controller: {spec: None}} be so clients can separate undefined controllers from
#         defined controllers with no return model.

#         """
#         if self._openapi_render_specs is None:
#             self._openapi_render_specs = {}

#             for controller_definition in self.app.controllers:
#                 controller = controller_definition.controller

#                 render_metadata = get_function_metadata(controller.render)
#                 render_model = render_metadata.get_render_model()

#                 spec = (
#                     self.openapi_schema_converter.get_model_json_schema(render_model)
#                     if render_model
#                     else None
#                 )
#                 self._openapi_render_specs[controller.__class__.__name__] = RenderSpec(
#                     url=None
#                     if isinstance(controller, LayoutControllerBase)
#                     else controller.url,
#                     view_path=str(controller.view_path),
#                     spec=spec,
#                 )

#         return self._openapi_render_specs

#     def sort_classes_by_dependency(self, classes: set[Type[T]]) -> list[Type[T]]:
#         """
#         Sorts classes based on their inheritance dependencies using topological sorting.
#         Classes will be ordered so that base classes appear before their derivatives.

#         """
#         # Create dependency graph mapping each class to its direct superclasses
#         graph = {
#             cls: {
#                 base for base in cls.__bases__
#                 if base in classes and base is not object
#             }
#             for cls in classes
#         }

#         # Use TopologicalSorter to get dependency-aware ordering
#         return list(TopologicalSorter(graph).static_order())

#     def _get_superclass_controllers(self, controller: ControllerBase):
#         # Validate that only ControllerBase subclasses have actions, otherwise we won't
#         # detect them in subsequent stages
#         superclasses : list[Type[ControllerBase]] = []

#         for superclass in controller.__class__.__mro__:
#             if issubclass(superclass, ControllerBase):
#                 superclasses.append(superclass)
#                 continue

#             # Any found actions in a non-controller class should be raised as an error
#             for name, func, _ in get_client_functions_cls(superclass):
#                 raise ValueError(
#                     f"Found action {name} in non-controller class {superclass}"
#                 )

#         return superclasses

#     @contextmanager
#     def catch_build_exception(self):
#         try:
#             yield
#         except BuildProcessException as e:
#             self.app._build_exception = e
#             raise


# class NamespaceResolver:
#     """
#     Handles class name resolution, using full module paths only when necessary to resolve conflicts.
#     """
#     def __init__(self):
#         self._name_to_classes: dict[str, set[Type]] = defaultdict(set)
#         self._class_to_identifier: dict[Type, str] = {}

#     def register_class(self, cls: Type) -> None:
#         """Register a class for namespace resolution."""
#         self._name_to_classes[cls.__name__].add(cls)

#     def resolve(self) -> None:
#         """
#         Resolve naming conflicts and generate final identifiers.
#         Called after all classes are registered.
#         """
#         self._class_to_identifier.clear()

#         for name, classes in self._name_to_classes.items():
#             if len(classes) == 1:
#                 # No conflict - use simple name
#                 cls = next(iter(classes))
#                 self._class_to_identifier[cls] = name
#             else:
#                 # Conflict - use full module path
#                 for cls in classes:
#                     self._class_to_identifier[cls] = f"{cls.__module__}.{cls.__name__}"

#     def get_identifier(self, cls: Type) -> str:
#         """Get the resolved identifier for a class."""
#         if cls not in self._class_to_identifier:
#             raise ValueError(f"Class {cls} not registered with namespace resolver")
#         return self._class_to_identifier[cls]

#     def get_typescript_name(self, cls: Type) -> str:
#         """Get the TypeScript-safe identifier for a class."""
#         return self.get_identifier(cls).replace('.', '_')
