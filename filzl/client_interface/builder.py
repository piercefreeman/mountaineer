from filzl.app import AppController
from pathlib import Path
from filzl.sideeffects import get_function_metadata
from filzl.client_interface.build_schemas import OpenAPIToTypeScriptConverter
from collections import defaultdict


class ClientBuilder:
    """
    Main entrypoint for building the auto-generated typescript code.

    """

    def __init__(self):
        self.openapi_schema_converter = OpenAPIToTypeScriptConverter()

    def build(self, app: AppController, view_root: Path):
        print("Will build", app.controllers)

        # Make sure our application definitions are in a valid state before we start
        # to build the client code
        self.validate_unique_paths(app)

        # TODO: Inject the global state into the view root

        for controller in app.controllers:
            metadata = get_function_metadata(controller.render)
            print("SHOULD BUILD", controller, controller.view_path, metadata)

            page_root = Path(controller.view_path).parent
            print(page_root)

            # Create the managed code directory if it doesn't exist
            managed_code_dir = page_root / "_server"
            managed_code_dir.mkdir(exist_ok=True)

            # Build the server state models
            if metadata.render_model:
                schemas = self.openapi_schema_converter.convert(metadata.render_model)
                print("SCHEMAS", schemas)
                (managed_code_dir / "models.ts").write_text(schemas)

    def validate_unique_paths(self, app: AppController):
        """
        Validate that all controller paths are unique. Otherwise we risk stomping
        on other server metadata that has already been written.

        """
        # Validation 1: Ensure that all view paths are unique
        view_counts = defaultdict(list)
        for controller in app.controllers:
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
        for controller in app.controllers:
            view_path = Path(controller.view_path)
            if not view_path.exists():
                raise ValueError(
                    f"View path {view_path} does not exist, ensure it is created before running the server"
                )
