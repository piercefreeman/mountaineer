from pathlib import Path

import pytest

from mountaineer.app import AppController
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.controller import ControllerBase


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


def test_use_layouts_property():
    """
    Test that the use_layouts property correctly controls whether layouts are applied.
    """
    app_controller = AppController(view_root=Path(""))
    
    # Create a layout controller
    layout_controller = ExampleLayoutController()
    app_controller.register(layout_controller)
    
    # Create a controller with layouts enabled (default)
    class WithLayoutsController(ControllerBase):
        url = "/with-layouts"
        view_path = "/app/with-layouts/page.tsx"
        
        def render(self) -> None:
            return None
    
    # Create a controller with layouts disabled
    class WithoutLayoutsController(ControllerBase):
        url = "/without-layouts"
        view_path = "/app/without-layouts/page.tsx"
        use_layouts = False
        
        def render(self) -> None:
            return None
    
    # Register both controllers
    with_layouts = WithLayoutsController()
    without_layouts = WithoutLayoutsController()
    app_controller.register(with_layouts)
    app_controller.register(without_layouts)
    
    # Check the hierarchy for the controller with layouts
    _, with_hierarchy = app_controller._view_hierarchy_for_controller(with_layouts)
    
    # Check the hierarchy for the controller without layouts
    _, without_hierarchy = app_controller._view_hierarchy_for_controller(without_layouts)
    
    # The controller with layouts should have itself in the hierarchy
    assert len(without_hierarchy) == 1
    assert without_hierarchy[0].controller == without_layouts
