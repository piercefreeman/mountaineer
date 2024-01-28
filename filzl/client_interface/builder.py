from filzl.app import AppController
from pathlib import Path
from filzl.sideeffects import get_function_metadata
from filzl.client_interface.build_schemas import OpenAPIToTypeScriptConverter
from collections import defaultdict
from fastapi.openapi.utils import get_openapi
from inflection import camelize


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

    def generate_model_definitions(self):
        for controller_definition in self.app.controllers:
            controller = controller_definition.controller
            router = controller_definition.router

            metadata = get_function_metadata(controller.render)
            print("SHOULD BUILD", controller, controller.view_path, metadata)

            # Create the managed code directory if it doesn't exist
            managed_code_dir = self.get_managed_code_dir(Path(controller.view_path))
            managed_code_dir.mkdir(exist_ok=True)

            # Build the server state models
            schemas = ""

            # We have to separately handle the model rendering because we intentionally
            # strip it from the OpenAPI payload. It's an internal detail, not one that's exposed
            # explicitly as part of the API.
            if metadata.render_model:
                schemas += self.openapi_schema_converter.convert(metadata.render_model)
                print("SCHEMAS", schemas)

            # temp_app = FastAPI()
            # temp_app.include_router(router)
            # print(get_openapi(title="", version="", routes=[router]))
            # schemas += self.openapi_schema_converter.convert(router)

            (managed_code_dir / "models.ts").write_text(schemas)

    def generate_global_model_imports(self):
        """
        The global definitions of the server context need to import all of the sub-models
        that are defined in the various pages. We create those imports here.

        """
        global_model_imports : list[str] = []

        for controller_definition in self.app.controllers:
            controller = controller_definition.controller

            # Get the relative path that will be required to import from this
            # sub-model
            controller_model_path = self.get_managed_code_dir(Path(controller.view_path)) / "models.ts"
            relative_import_path = controller_model_path.relative_to(self.view_root)

            metadata = get_function_metadata(controller.render)
            if metadata.render_model:
                controller_name = camelize(controller.__class__.__name__)
                typescript_name = camelize(metadata.render_model.__name__)
                # We need to prefix the model with our controller, since we enforce controller uniqueness
                # but not response model name uniqueness
                global_model_imports.append(
                    f"import type {{ {typescript_name} as {controller_name}{typescript_name} }} from '../{relative_import_path}'"
                )

        schema = "\n".join(global_model_imports)

        # Write to disk in the view root directory
        managed_dir = self.get_managed_code_dir(self.view_root)
        managed_dir.mkdir(exist_ok=True)
        (managed_dir / "models.ts").write_text(schema)

    def get_managed_code_dir(self, path: Path):
        # If the path is to a file, we want to get the parent directory
        # so that we can create the managed code directory
        if path.is_file():
            path = path.parent
        managed_code_dir = path / "_server"
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
