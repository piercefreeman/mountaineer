from enum import Enum
from pathlib import Path
from typing import List, Sequence

import pytest

from mountaineer.actions.passthrough_dec import passthrough
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.app import AppController
from mountaineer.client_builder.file_generators.base import ParsedController
from mountaineer.client_builder.file_generators.globals import (
    GlobalControllerGenerator,
    GlobalLinkGenerator,
)
from mountaineer.client_builder.parser import (
    ControllerParser,
    ControllerWrapper,
    EnumWrapper,
    ModelWrapper,
)
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.paths import ManagedViewPath
from mountaineer.render import RenderBase


# Test Classes
class StatusEnum(Enum):
    ACTIVE = "active"
    PENDING = "pending"
    INACTIVE = "inactive"


class MainModel(RenderBase):
    name: str
    status: StatusEnum


class ChildModel(MainModel):
    child_field: str
    count: int


class DependentModel(MainModel):
    base: MainModel
    child: ChildModel
    current_status: StatusEnum


# Controllers
class BaseController(ControllerBase):
    @passthrough
    def base_action(self) -> MainModel:  # type: ignore
        pass


class ChildController(BaseController):
    url: str = "/child"
    view_path = "/child.tsx"

    async def render(self) -> DependentModel:  # type: ignore
        pass

    @sideeffect
    def update(self, data: ChildModel) -> DependentModel:  # type: ignore
        pass


class LayoutController(LayoutControllerBase):
    view_path = "/layout.tsx"

    async def render(self) -> MainModel:  # type: ignore
        pass


@pytest.fixture
def managed_path(tmp_path: Path) -> ManagedViewPath:
    return ManagedViewPath(tmp_path)


@pytest.fixture
def controller_parser() -> ControllerParser:
    return ControllerParser()


@pytest.fixture
def controller_wrappers(controller_parser: ControllerParser) -> list[ControllerWrapper]:
    # Concrete instances should be mounted to an AppController to augment
    # some of the runtime type information
    app_controller = AppController(view_root=Path())
    app_controller.register(ChildController())
    app_controller.register(LayoutController())

    return [
        controller_parser.parse_controller(ChildController),
        controller_parser.parse_controller(LayoutController),
    ]


# Tests
class TestGlobalControllerGenerator:
    @pytest.fixture
    def generator(
        self,
        managed_path: ManagedViewPath,
        controller_wrappers: List[ControllerWrapper],
    ) -> GlobalControllerGenerator:
        return GlobalControllerGenerator(
            managed_path=managed_path, controller_wrappers=controller_wrappers
        )

    def test_model_enum_graph_resolution(
        self, generator: GlobalControllerGenerator
    ) -> None:
        """Test that models and enums are sorted correctly"""
        # Get embedded types
        controllers = ControllerWrapper.get_all_embedded_controllers(
            generator.controller_wrappers
        )
        embedded = ControllerWrapper.get_all_embedded_types(
            controllers, include_superclasses=True
        )

        # Sort them
        sorted_items = generator._build_model_enum_graph(
            embedded.models, embedded.enums
        )

        # Hierarchy is:
        # StatusEnum
        # MainModel <- DependentModel
        #           <- ChildModel
        # Verify StatusEnum comes before BaseModel
        # Enums come before models and parents come before their subclasses
        enum_idx = self.get_item_order(sorted_items, "StatusEnum")
        main_model_idx = self.get_item_order(sorted_items, "MainModel")
        assert enum_idx < main_model_idx

        child_model_idx = self.get_item_order(sorted_items, "ChildModel")
        assert main_model_idx < child_model_idx

        dependent_model_idx = self.get_item_order(sorted_items, "DependentModel")
        assert main_model_idx < dependent_model_idx

    def test_controller_graph_resolution(
        self, generator: GlobalControllerGenerator
    ) -> None:
        """Test that controllers are sorted correctly"""
        controllers = ControllerWrapper.get_all_embedded_controllers(
            generator.controller_wrappers
        )
        sorted_controllers = generator._build_controller_graph(controllers)

        base_idx = self.get_item_order(sorted_controllers, "BaseController")
        child_idx = self.get_item_order(sorted_controllers, "ChildController")

        # Base should come before Child
        assert base_idx < child_idx

    def test_script_generation(self, generator: GlobalControllerGenerator) -> None:
        """Test the complete script generation"""
        blocks = generator.script()
        content = "\n".join(block.content for block in blocks)

        # Verify models are generated
        assert "export interface MainModel" in content
        assert "export interface ChildModel extends MainModel" in content
        assert "export interface DependentModel extends MainModel" in content

        # Verify enum is generated
        assert "export enum StatusEnum" in content
        assert "ACTIVE = " in content

        # Verify controllers are generated
        assert "export interface BaseController" in content
        assert "export interface ChildController extends BaseController" in content

        # Verify layout controller is included
        assert "export interface LayoutController" in content

    def get_item_order(
        self,
        sorted_items: Sequence[ModelWrapper | EnumWrapper | ControllerWrapper],
        raw_name: str,
    ):
        return next(
            i for i, item in enumerate(sorted_items) if item.name.raw_name == raw_name
        )


class TestGlobalLinkGenerator:
    @pytest.fixture
    def parsed_controllers(
        self, controller_parser: ControllerParser, managed_path: ManagedViewPath
    ) -> List[ParsedController]:
        (managed_path / "child").mkdir()
        (managed_path / "layout").mkdir()

        return [
            ParsedController(
                wrapper=controller_parser.parse_controller(ChildController),
                view_path=ManagedViewPath(managed_path / "child"),
                is_layout=False,
            ),
            ParsedController(
                wrapper=controller_parser.parse_controller(LayoutController),
                view_path=ManagedViewPath(managed_path / "layout"),
                is_layout=True,
            ),
        ]

    @pytest.fixture
    def generator(
        self, managed_path: ManagedViewPath, parsed_controllers: List[ParsedController]
    ) -> GlobalLinkGenerator:
        return GlobalLinkGenerator(
            managed_path=managed_path, parsed_controllers=parsed_controllers
        )

    def test_script_generation(self, generator: GlobalLinkGenerator) -> None:
        """Test link aggregator generation"""
        blocks = generator.script()
        content = "\n".join(block.content for block in blocks)

        # Verify imports
        assert "import { getLink as ChildControllerGetLinks }" in content

        # Verify layout controller is excluded
        assert "LayoutControllerGetLinks" not in content

        # Verify link generator object
        assert "const linkGenerator = {" in content
        assert "childController: ChildControllerGetLinks" in content
        assert "export default linkGenerator" in content
