from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from mountaineer.app import AppController
from mountaineer.client_builder.builder import ClientBuilder
from mountaineer.controller import ControllerBase


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


@pytest.fixture(scope="function")
def simple_app_controller():
    with TemporaryDirectory() as temp_dir_name:
        temp_view_path = Path(temp_dir_name)
        (temp_view_path / "detail").mkdir()

        # Simple view files
        (temp_view_path / "page.tsx").write_text("")
        (temp_view_path / "detail" / "page.tsx").write_text("")

        app_controller = AppController(view_root=temp_view_path)
        app_controller.register(ExampleHomeController())
        app_controller.register(ExampleDetailController())
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


def test_generate_view_servers(builder: ClientBuilder):
    builder.generate_view_servers()
