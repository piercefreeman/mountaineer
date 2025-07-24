from pathlib import Path

import pytest
from mountaineer.controller import ControllerBase
from pathlib import Path

import pytest
from pydantic import BaseModel

from mountaineer.controller import ControllerBase
from mountaineer.render import (
    RenderBase,
)
from mountaineer.app import AppController
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.actions.passthrough_dec import passthrough
from mountaineer.actions.fields import get_function_metadata


class StubRenderBase(RenderBase):
    pass


class StubController(ControllerBase):
    view_path = "/page.tsx"

    def render(self):
        return StubRenderBase()

def test_get_action_url(tmp_path: Path):
    class SideEffectController(ControllerBase):
        url = "/test"
        view_path = "/test.tsx"

        def __init__(self):
            super().__init__()

        @sideeffect
        def my_sideeffect(self) -> None:
            pass

        def render(self) -> StubRenderBase:
            return StubRenderBase()

    app = AppController(view_root=tmp_path)
    controller = SideEffectController()
    app.register(controller)

    assert controller.get_action_url(controller.my_sideeffect) == "/internal/api/side_effect_controller/my_sideeffect"

def test_get_action_url_unregistered():
    class SideEffectController(ControllerBase):
        url = "/test"
        view_path = "/test.tsx"

        def __init__(self):
            super().__init__()

        @sideeffect
        def my_sideeffect(self) -> None:
            pass

        def render(self) -> StubRenderBase:
            return StubRenderBase()

    controller = SideEffectController()
    with pytest.raises(ValueError):
        controller.get_action_url(controller.my_sideeffect)


def test_resolve_paths(tmp_path: Path):
    view_base = tmp_path / "views"
    ssr_base = view_base / "_ssr"
    static_base = view_base / "_static"

    controller = StubController()
    assert not controller.resolve_paths(view_base)

    # Now create an actual view path that we can sniff
    # This will get further in the pipeline but still won't be valid
    # because we don't have any of the global script files
    view_base.mkdir()
    assert not controller.resolve_paths(view_base)

    # Now we create the SSR script file
    ssr_base.mkdir()
    (ssr_base / "stub_controller.js").touch()
    (ssr_base / "stub_controller.js.map").touch()
    assert not controller.resolve_paths(view_base)

    # Our hash has to be exactly 32 digits to match the regex
    static_base.mkdir()
    (static_base / "stub_controller.js").touch()
    (static_base / "stub_controller.js.map").touch()
    assert controller.resolve_paths(view_base)

    # Now ensure that the paths are correctly set
    assert controller._view_base_path == view_base
    assert controller._ssr_path == ssr_base / "stub_controller.js"
    assert len(controller._bundled_scripts) == 1
    assert controller._bundled_scripts[0].startswith("stub_controller.js?v=")
