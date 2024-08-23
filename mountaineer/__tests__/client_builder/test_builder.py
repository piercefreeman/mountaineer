from dataclasses import asdict, replace
from json import dumps as json_dumps, loads as json_loads
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pydantic import BaseModel

from mountaineer.actions import sideeffect
from mountaineer.app import AppController
from mountaineer.client_builder.builder import ClientBuilder
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.render import RenderBase


class ExampleHomeController(ControllerBase):
    url = "/"
    view_path = "/page.tsx"

    def render(self) -> None:
        return None


class ExampleDetailController(ControllerBase):
    url = "/detail/{detail_id}/"
    view_path = "/detail/page.tsx"

    def render(self) -> None:
        return None


@pytest.fixture
def home_controller():
    return ExampleHomeController()


@pytest.fixture
def detail_controller():
    return ExampleDetailController()


@pytest.fixture(scope="function")
def simple_app_controller(
    home_controller: ExampleHomeController, detail_controller: ExampleDetailController
):
    with TemporaryDirectory() as temp_dir_name:
        temp_view_path = Path(temp_dir_name)
        (temp_view_path / "detail").mkdir()

        # Simple view files
        (temp_view_path / "page.tsx").write_text("")
        (temp_view_path / "detail" / "page.tsx").write_text("")

        app_controller = AppController(view_root=temp_view_path)
        app_controller.register(home_controller)
        app_controller.register(detail_controller)
        yield app_controller


@pytest.fixture
def builder(simple_app_controller: AppController):
    return ClientBuilder(simple_app_controller)


def test_generate_static_files(builder: ClientBuilder):
    builder.generate_static_files()


def test_generate_model_definitions(builder: ClientBuilder):
    builder.generate_model_definitions()


def test_generate_action_definitions(builder: ClientBuilder):
    builder.generate_action_definitions()


def test_generate_view_definitions(builder: ClientBuilder):
    builder.generate_link_shortcuts()


def test_generate_link_aggregator(builder: ClientBuilder):
    builder.generate_link_aggregator()


def test_generate_link_aggregator_ignores_layout(builder: ClientBuilder):
    class ExampleLayout(LayoutControllerBase):
        view_path = "/test.tsx"

        async def render(self) -> None:
            pass

    builder.app.register(ExampleLayout())
    builder.generate_link_aggregator()

    global_code_dir = builder.view_root.get_managed_code_dir()
    global_links = (global_code_dir / "links.ts").read_text()
    assert "ExampleLayout" not in global_links
    assert "ExampleHomeControllerGetLinks" in global_links
    assert "ExampleDetailControllerGetLinks" in global_links


def test_generate_view_servers(builder: ClientBuilder):
    builder.generate_view_servers()


@pytest.mark.parametrize("empty_links", [True, False])
def test_generate_index_file_ignores_empty(builder: ClientBuilder, empty_links: bool):
    # Create some stub files. We simulate a case where the links file
    # is created but empty
    file_contents = "import React from 'react';\n"
    for controller_definition in builder.app.controllers:
        controller_code_dir = builder.view_root.get_controller_view_path(
            controller_definition.controller
        ).get_managed_code_dir()

        (controller_code_dir / "actions.ts").write_text(file_contents)
        (controller_code_dir / "models.ts").write_text(file_contents)
        (controller_code_dir / "useServer.ts").write_text(file_contents)
        if empty_links:
            (controller_code_dir / "links.ts").write_text("")

    builder.generate_index_file()

    # Read the index file for each controller
    for controller_definition in builder.app.controllers:
        controller_code_dir = builder.view_root.get_controller_view_path(
            controller_definition.controller
        ).get_managed_code_dir()

        index_file = controller_code_dir / "index.ts"
        assert index_file.exists()
        imported_dependencies = index_file.read_text().split("\n")
        assert imported_dependencies == [
            "export * from './actions';",
            "export * from './models';",
            "export * from './useServer';",
        ]


def test_cache_is_outdated_no_cache(builder: ClientBuilder):
    # No cache
    builder.build_cache = None
    assert builder.cache_is_outdated() is True


def test_cache_is_outdated_no_existing_data(builder: ClientBuilder, tmp_path: Path):
    builder.build_cache = tmp_path

    assert builder.cache_is_outdated() is True

    # Ensure that we've written to the cache
    cache_path = tmp_path / "client_builder_openapi.json"
    assert cache_path.exists()
    assert set(json_loads(cache_path.read_text()).keys()) == {
        "ExampleHomeController",
        "ExampleDetailController",
    }


def test_cache_is_outdated_existing_data(
    builder: ClientBuilder,
    tmp_path: Path,
    home_controller: ExampleHomeController,
    detail_controller: ExampleDetailController,
):
    builder.build_cache = tmp_path

    # Ensure that we've written to the cache
    cache_path = tmp_path / "client_builder_openapi.json"
    cache_path.write_text(
        json_dumps(
            {
                "ExampleHomeController": {
                    "action": builder.openapi_action_specs[home_controller],
                    "render": asdict(builder.openapi_render_specs[home_controller]),
                },
                "ExampleDetailController": {
                    "action": builder.openapi_action_specs[detail_controller],
                    "render": asdict(builder.openapi_render_specs[detail_controller]),
                },
            },
            sort_keys=True,
        )
    )

    assert builder.cache_is_outdated() is False


def test_cache_is_outdated_url_change(
    builder: ClientBuilder,
    tmp_path: Path,
    home_controller: ExampleHomeController,
    detail_controller: ExampleDetailController,
):
    builder.build_cache = tmp_path

    cache_path = tmp_path / "client_builder_openapi.json"
    cache_path.write_text(
        json_dumps(
            {
                "ExampleHomeController": {
                    "action": builder.openapi_action_specs[home_controller],
                    "render": asdict(
                        # Only modify the render attribute. Simulate a user changing the URL
                        # of a component, which does require a FE rebuild.
                        replace(
                            builder.openapi_render_specs[home_controller],
                            url="/new_url",
                        )
                    ),
                },
                "ExampleDetailController": {
                    "action": builder.openapi_action_specs[detail_controller],
                    "render": asdict(builder.openapi_render_specs[detail_controller]),
                },
            },
            sort_keys=True,
        )
    )

    assert builder.cache_is_outdated() is True


def test_validate_unique_paths_exact_definition(
    builder: ClientBuilder,
):
    """
    Two controllers can't manage the same view path.

    """

    class ConflictingDetailController(ControllerBase):
        url = "/detail/other_url/"
        view_path = "/detail/page.tsx"

        def render(self) -> None:
            return None

    builder.app.register(ConflictingDetailController())

    # Raises for the same exact view path
    with pytest.raises(
        ValueError, match="duplicate view paths under controller management"
    ):
        builder.validate_unique_paths()


def test_validate_unique_paths_conflicting_layout(
    builder: ClientBuilder,
):
    """
    Layouts need to be placed in their own directory. Even if the literal paths
    under management are different we still need to throw a validation error.

    """

    class ConflictingLayoutController(LayoutControllerBase):
        view_path = "/detail/layout.tsx"

        def render(self) -> None:
            return None

    builder.app.register(ConflictingLayoutController())

    # Raises for the same exact view path
    with pytest.raises(
        ValueError, match="duplicate view paths under controller management"
    ):
        builder.validate_unique_paths()


def test_generate_controller_schema_sideeffect_required_attributes(
    builder: ClientBuilder,
):
    """
    Ensure that we treat @sideeffect and @passthrough return models like
    the render model, where we make all their attributes required since
    we are guaranteed that the push payload from the server will fully
    hydrate the default values.

    """

    class DataBundle(BaseModel):
        a: int
        b: str

    class SimpleRender(RenderBase):
        a: list[DataBundle] = []

    class SimpleReturn(BaseModel):
        b: list[DataBundle] = []

    class SideEffectController(ControllerBase):
        url = "/sideeffect/"
        view_path = "/sideeffect/page.tsx"

        def render(self) -> SimpleRender:
            return SimpleRender(a=[DataBundle(a=1, b="1")])

        @sideeffect
        def my_sideeffect(self) -> SimpleReturn:
            return SimpleReturn(b=[DataBundle(a=2, b="2")])

    controller = SideEffectController()
    builder.app.register(controller)

    schemas = builder._generate_controller_schema(controller)

    assert set(schemas.keys()) == {
        "SimpleRender",
        "DataBundle",
        "MySideeffectResponse",
        "MySideeffectResponseSideEffect",
        "MySideeffectResponsePassthrough",
    }

    assert "a: Array<DataBundle>" in schemas["SimpleRender"]
    assert "a: Array<DataBundle>" in schemas["MySideeffectResponseSideEffect"]
    assert "b: Array<DataBundle>" in schemas["MySideeffectResponsePassthrough"]
