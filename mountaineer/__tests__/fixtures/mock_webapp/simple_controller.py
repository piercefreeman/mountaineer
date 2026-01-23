from pathlib import Path

from mountaineer import Mountaineer, ConfigBase, ControllerBase


class TestController(ControllerBase):
    view_path = "/test_controller/page.tsx"
    url = "/"

    async def render(self) -> None:
        pass


# We need a development config to test dev utilities
class SimpleConfig(ConfigBase):
    pass


config = SimpleConfig()

test_controller = Mountaineer(
    view_root=Path(__file__).parent.joinpath("views"),
    config=config,
)
test_controller.register(TestController())
