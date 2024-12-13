from enum import Enum
from typing import Iterator, List, Sequence, Type

import pytest
from pydantic import BaseModel

from mountaineer.actions.passthrough_dec import passthrough
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.client_builder.file_generators.base import ParsedController
from mountaineer.client_builder.file_generators.globals import (
    GlobalControllerGenerator,
    GlobalLinkGenerator,
)
from mountaineer.client_builder.parser import ControllerParser, ControllerWrapper
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.paths import ManagedViewPath


# Test Classes
class StatusEnum(Enum):
    ACTIVE: str = "active"
    PENDING: str = "pending"
    INACTIVE: str = "inactive"


class MainModel(BaseModel):
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
    def base_action(self) -> MainModel:
        pass


class ChildController(BaseController):
    url: str = "/child"

    async def render(self) -> DependentModel:
        pass

    @sideeffect
    def update(self, data: ChildModel) -> DependentModel:
        pass


class LayoutController(LayoutControllerBase):
    async def render(self) -> MainModel:
        pass


# Tests
class TestGlobalControllerGenerator:
    @pytest.fixture
    def managed_path(self) -> ManagedViewPath:
        return ManagedViewPath("/test/root/controllers.ts")

    @pytest.fixture
    def controller_parser(self) -> ControllerParser:
        return ControllerParser()

    @pytest.fixture
    def controller_wrappers(
        self, controller_parser: ControllerParser
    ) -> List[ControllerWrapper]:
        return [
            controller_parser.parse_controller(ChildController),
            controller_parser.parse_controller(LayoutController),
        ]

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
        controllers: Sequence[
            Type[ControllerBase]
        ] = ControllerWrapper.get_all_embedded_controllers(
            generator.controller_wrappers
        )
        embedded = ControllerWrapper.get_all_embedded_types(
            controllers, include_superclasses=True
        )

        # Sort them
        sorted_items = generator._build_model_enum_graph(
            embedded.models, embedded.enums
        )

        # Verify StatusEnum comes before BaseModel
        enum_idx: int = next(
            i
            for i, item in enumerate(sorted_items)
            if item.name.raw_name == "StatusEnum"
        )
        base_model_idx: int = next(
            i
            for i, item in enumerate(sorted_items)
            if item.name.raw_name == "BaseModel"
        )
        assert enum_idx < base_model_idx

        # Verify BaseModel comes before ChildModel
        child_model_idx: int = next(
            i
            for i, item in enumerate(sorted_items)
            if item.name.raw_name == "ChildModel"
        )
        assert base_model_idx < child_model_idx

        # Verify both models come before DependentModel
        dependent_idx: int = next(
            i
            for i, item in enumerate(sorted_items)
            if item.name.raw_name == "DependentModel"
        )
        assert child_model_idx < dependent_idx

    def test_controller_graph_resolution(
        self, generator: GlobalControllerGenerator
    ) -> None:
        """Test that controllers are sorted correctly"""
        controllers: Sequence[
            Type[ControllerBase]
        ] = ControllerWrapper.get_all_embedded_controllers(
            generator.controller_wrappers
        )
        sorted_controllers = generator._build_controller_graph(controllers)

        # Find indices
        base_idx: int = next(
            i
            for i, c in enumerate(sorted_controllers)
            if c.name.raw_name == "BaseController"
        )
        child_idx: int = next(
            i
            for i, c in enumerate(sorted_controllers)
            if c.name.raw_name == "ChildController"
        )

        # Base should come before Child
        assert base_idx < child_idx

    def test_script_generation(self, generator: GlobalControllerGenerator) -> None:
        """Test the complete script generation"""
        blocks: Iterator[any] = generator.script()
        content: str = "\n".join(block.content for block in blocks)

        # Verify models are generated
        assert "export interface BaseModel" in content
        assert "export interface ChildModel extends BaseModel" in content
        assert "export interface DependentModel" in content

        # Verify enum is generated
        assert "export enum StatusEnum" in content
        assert "ACTIVE = " in content

        # Verify controllers are generated
        assert "export interface BaseController" in content
        assert "export interface ChildController extends BaseController" in content

        # Verify layout controller is included
        assert "export interface LayoutController" in content


class TestGlobalLinkGenerator:
    @pytest.fixture
    def managed_path(self) -> ManagedViewPath:
        return ManagedViewPath("/test/root/links.ts")

    @pytest.fixture
    def controller_parser(self) -> ControllerParser:
        return ControllerParser()

    @pytest.fixture
    def parsed_controllers(
        self, controller_parser: ControllerParser
    ) -> List[ParsedController]:
        return [
            ParsedController(
                wrapper=controller_parser.parse_controller(ChildController),
                view_path=ManagedViewPath("/test/views/child"),
                is_layout=False,
            ),
            ParsedController(
                wrapper=controller_parser.parse_controller(LayoutController),
                view_path=ManagedViewPath("/test/views/layout"),
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
        content: str = "\n".join(line for block in blocks for line in block.lines)

        # Verify imports
        assert "import { getLink as ChildControllerGetLinks }" in content

        # Verify layout controller is excluded
        assert "LayoutControllerGetLinks" not in content

        # Verify link generator object
        assert "const linkGenerator = {" in content
        assert "childController: ChildControllerGetLinks" in content
        assert "export default linkGenerator" in content
