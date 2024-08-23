from pathlib import Path

from mountaineer import AppController, ControllerBase


class TestController(ControllerBase):
    view_path = "/test.tsx"
    url = "/"

    async def render(self) -> None:
        pass


test_controller = AppController(view_root=Path(__file__).parent.joinpath("views"))
test_controller.register(TestController())
