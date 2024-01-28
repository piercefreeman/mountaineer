from filzl.app import AppController
from pathlib import Path
from filzl.sideeffects import get_function_metadata
from filzl.client_interface.build_schemas import OpenAPIToTypeScriptConverter
from collections import defaultdict
from inflection import camelize, underscore
from inspect import isclass
from pydantic import BaseModel


class ClientBuilder:
    """
    Main entrypoint for building the auto-generated typescript code.

    """

    def __init__(self, app: AppController, view_root: Path):
        self.openapi_schema_converter = OpenAPIToTypeScriptConverter()
        self.app = app
        self.view_root = view_root

    def build(self):
        print("Will build", self.app.controllers)

        # Make sure our application definitions are in a valid state before we start
        # to build the client code
        self.validate_unique_paths()

        self.generate_model_definitions()
        self.generate_global_model_imports()
        self.generate_server_provider()

    def generate_model_definitions(self):
        """
        Generate the interface type definitions for the models. These most closely
        apply to the controller that they're defined within, so we create the files
        directly within the controller's view directory.

        """
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller

            metadata = get_function_metadata(controller.render)
            print("SHOULD BUILD", controller, controller.view_path, metadata)

            # Create the managed code directory if it doesn't exist
            managed_code_dir = self.get_managed_code_dir(Path(controller.view_path))

            # Build the server state models, enforce unique schema names so we avoid interface duplicates
            # if they're defined in multiple places
            schemas: dict[str, str] = {}

            # We have to separately handle the model rendering because we intentionally
            # strip it from the OpenAPI payload. It's an internal detail, not one that's exposed
            # explicitly as part of the API.
            if metadata.render_model:
                schemas = {
                    **schemas,
                    **self.openapi_schema_converter.convert(metadata.render_model),
                }

            for _, fn, _ in controller._get_client_functions():
                return_model = fn.__annotations__.get("return")
                if (
                    return_model
                    and isclass(return_model)
                    and issubclass(return_model, BaseModel)
                ):
                    schemas = {
                        **schemas,
                        **self.openapi_schema_converter.convert(return_model),
                    }

            # We put in one big models.ts file to enable potentially cyclical dependencies
            (managed_code_dir / "models.ts").write_text(
                "\n\n".join(
                    [
                        schema
                        for _, schema in sorted(schemas.items(), key=lambda x: x[0])
                    ]
                )
            )

    def generate_global_model_imports(self):
        """
        The global definitions of the server context need to import all of the sub-models
        that are defined in the various pages. We create those imports here.

        """
        global_model_imports: list[str] = []

        for controller_definition in self.app.controllers:
            controller = controller_definition.controller

            # Get the relative path that will be required to import from this
            # sub-model
            controller_model_path = (
                self.get_managed_code_dir(Path(controller.view_path)) / "models.ts"
            )
            relative_import_path = controller_model_path.relative_to(self.view_root)

            metadata = get_function_metadata(controller.render)
            if metadata.render_model:
                controller_name = camelize(controller.__class__.__name__)
                typescript_name = camelize(metadata.render_model.__name__)
                # We need to prefix the model with our controller, since we enforce controller uniqueness
                # but not response model name uniqueness
                global_model_imports.append(
                    f"export type {{ {typescript_name} as {controller_name}{typescript_name} }} from '../{relative_import_path}'"
                )

        schema = "\n".join(global_model_imports)

        # Write to disk in the view root directory
        managed_dir = self.get_managed_code_dir(self.view_root)
        (managed_dir / "models.ts").write_text(schema)

    def generate_server_provider(self):
        """
        Generate the server provider that will be used to initialize the server
        at the root of the application.

        """
        chunks = []

        # Step 1: Global imports that will be required
        chunks.append(
            "import React, { useContext, useState, ReactNode } from 'react';\n"
            + "import type * as ControllerTypes from './models';"
        )

        # Step 2: Now we create the server state. This is the common payload that
        # will represent all of the server state that's available to the client. This will
        # only ever be filled in with the current page, but having a global element will allow
        # us to use one provider that's still typehinted to each view.
        server_state_lines = []
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller

            controller_name = camelize(controller.__class__.__name__)
            controller_name_global = underscore(controller.__class__.__name__).upper()

            render_metadata = get_function_metadata(controller.render)
            render_model_name = camelize(render_metadata.render_model.__name__)

            server_state_lines.append(
                f"{controller_name_global}?: ControllerTypes.{controller_name}{render_model_name}"
            )
        chunks.append(
            "interface ServerState {\n"
            + ",\n".join([f"  {line}" for line in server_state_lines])
            + "\n}"
        )

        # Step 3: Define the server context provider
        chunks.append(
            "export const ServerContext = useContext<{\n"
            + "  serverState: ServerState\n"
            + "  setServerState: (state: ServerState) => void\n"
            + "}>(undefined as any)"
        )

        # Step 4: Define the server provider
        server_provider_state_lines = []
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller
            controller_name_global = underscore(controller.__class__.__name__).upper()

            server_provider_state_lines.append(
                f"{controller_name_global}: GLOBAL_STATE[{controller_name_global}]"
            )
        chunks.append(
            "export const ServerProvider = ({ children }: { children: ReactNode }) => {\n"
            + "const [serverState, setServerState] = useState<ServerState>({\n"
            + ",\n".join(
                f"  {line}" for line in server_provider_state_lines
            )
            + "\n});\n"
            + "return <ServerContext.Provider\n"
            + "serverState={serverState}\n"
            + "setServerState={setServerState}>\n"
            + "{children}</ServerContext.Provider>\n"
            + "};"
        )

        managed_dir = self.get_managed_code_dir(self.view_root)
        (managed_dir / "server.tsx").write_text("\n\n".join(chunks))

    def get_managed_code_dir(self, path: Path):
        # If the path is to a file, we want to get the parent directory
        # so that we can create the managed code directory
        # We also create the managed code directory if it doesn't exist so all subsequent
        # calls can immediately start writing to it
        if path.is_file():
            path = path.parent
        managed_code_dir = path / "_server"
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
            view_counts[Path(controller.view_path).parent].append(controller)
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
            view_path = Path(controller.view_path)
            if not view_path.exists():
                raise ValueError(
                    f"View path {view_path} does not exist, ensure it is created before running the server"
                )
