from filzl.app import AppController
from pathlib import Path
from filzl.sideeffects import METADATA_ATTRIBUTE

def build_client_code(app: AppController, view_root: Path):
    print("Will build", app.controllers)

    # TODO: Inject the global state into the view root

    for controller in app.controllers:
        metadata = getattr(controller.render, METADATA_ATTRIBUTE, None)
        if not metadata:
            raise ValueError(f"Controller {controller}.render has no metadata")

        print("SHOULD BUILD", controller, controller.view_path, metadata)
