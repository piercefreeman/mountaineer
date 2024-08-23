from pathlib import Path

import pytest

from mountaineer.app import AppController
from mountaineer.controller_layout import LayoutControllerBase


class ExampleLayoutController(LayoutControllerBase):
    view_path = "/test.tsx"

    async def render(self) -> None:
        pass


@pytest.mark.asyncio
async def test_disallows_direct_rendering():
    """
    Layouts can't be rendered directly. They're intended for use
    only as pages wrappers.

    """
    layout_controller = ExampleLayoutController()

    with pytest.raises(NotImplementedError):
        await layout_controller._generate_html(global_metadata={})

    with pytest.raises(NotImplementedError):
        layout_controller._generate_ssr_html({})


def test_layout_registration():
    """
    Layout controllers must register with the AppController for them
    to be used by client render controllers.

    """
    app_controller = AppController(view_root=Path(""))
    layout_controller = ExampleLayoutController()

    app_controller.register(layout_controller)
    assert len(app_controller.controllers) == 1

    assert app_controller.controllers[0].controller == layout_controller
