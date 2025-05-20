from inspect import Parameter, signature
from pathlib import Path

import pytest
from fastapi import APIRouter

from mountaineer.app import AppController, ControllerDefinition
from mountaineer.controller import ControllerBase
from mountaineer.graph.app_graph import ControllerRoute


class TargetController(ControllerBase):
    url = "/target"

    async def render(self) -> None:
        pass


class ReferenceController(ControllerBase):
    url = "/reference"

    async def render(self) -> None:
        pass


def test_merge_render_signatures():
    def target_fn(a: int, b: int):
        pass

    # Partial overlap with (a) and inclusion of a new variable
    def reference_fn(a: int, c: int):
        pass

    app = AppController(view_root=Path(""))

    target_definition = ControllerDefinition(
        controller=TargetController(),
        route=ControllerRoute(
            router=APIRouter(),
            view_route=target_fn,
            url_prefix="/target_prefix",
            render_router=APIRouter(),
        ),
        graph=app.graph,
    )
    reference_definition = ControllerDefinition(
        controller=ReferenceController(),
        route=ControllerRoute(
            router=APIRouter(),
            view_route=reference_fn,
            url_prefix="/reference_prefix",
            render_router=APIRouter(),
        ),
        graph=app.graph,
    )

    assert target_definition.route is not None
    assert reference_definition.route is not None

    app.graph._merge_render_signatures(
        target_definition, reference_controller=reference_definition
    )

    assert list(signature(target_definition.route.view_route).parameters.values()) == [
        Parameter("a", Parameter.POSITIONAL_OR_KEYWORD, annotation=int),
        Parameter("b", Parameter.POSITIONAL_OR_KEYWORD, annotation=int),
        # Items only in the reference function should be included as kwargs
        Parameter("c", Parameter.KEYWORD_ONLY, annotation=int, default=Parameter.empty),
    ]


def test_merge_render_signatures_conflicting_types():
    """
    If the two functions share a parameter, it must be typehinted with the
    same type in both functions.

    """

    def target_fn(a: int, b: int):
        pass

    # Partial overlap with (a) and inclusion of a new variable
    def reference_fn(a: str, c: int):
        pass

    app = AppController(view_root=Path(""))

    target_definition = ControllerDefinition(
        controller=TargetController(),
        route=ControllerRoute(
            router=APIRouter(),
            view_route=target_fn,
            url_prefix="/target_prefix",
            render_router=APIRouter(),
        ),
        graph=app.graph,
    )
    reference_definition = ControllerDefinition(
        controller=ReferenceController(),
        route=ControllerRoute(
            router=APIRouter(),
            view_route=reference_fn,
            url_prefix="/reference_prefix",
            render_router=APIRouter(),
        ),
        graph=app.graph,
    )

    assert target_definition.route is not None
    assert reference_definition.route is not None

    with pytest.raises(TypeError, match="Conflicting types"):
        app.graph._merge_render_signatures(
            target_definition, reference_controller=reference_definition
        )
