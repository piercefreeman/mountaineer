from mountaineer.controller import ControllerBase
from mountaineer.render import (
    RenderBase,
)


class StubRenderBase(RenderBase):
    pass


class StubController(ControllerBase):
    view_path = "/page.tsx"

    def render(self):
        return StubRenderBase()


def test_controller_only_declares_view_and_script_name():
    controller = StubController()
    assert controller.view_path == "/page.tsx"
    assert controller.script_name == "stub_controller"
