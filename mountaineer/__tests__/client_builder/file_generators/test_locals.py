from enum import Enum
from typing import Any, List

import pytest
from fastapi import File
from pydantic import BaseModel

from mountaineer.actions.passthrough_dec import passthrough
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.client_builder.file_generators.base import CodeBlock
from mountaineer.client_builder.file_generators.locals import (
    LocalActionGenerator,
    LocalGeneratorBase,
    LocalIndexGenerator,
    LocalLinkGenerator,
    LocalModelGenerator,
    LocalUseServerGenerator,
)
from mountaineer.client_builder.parser import (
    ControllerParser,
    ControllerWrapper,
)
from mountaineer.controller import ControllerBase
from mountaineer.exceptions import APIException
from mountaineer.paths import ManagedViewPath
from mountaineer.render import RenderBase


# Test Models and Enums
class TestStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class TestException(APIException):
    status_code: int = 400

    class InternalModel(BaseModel):
        message: str
        code: int


class TestBaseModel(BaseModel):
    name: str
    status: TestStatus


class TestRequestModel(BaseModel):
    query: str
    limit: int = 10


class TestResponseModel(BaseModel):
    results: List[str]
    total: int


class TestRenderModel(RenderBase):
    title: str
    items: List[TestBaseModel]


# Test Controllers
class TestBaseController(ControllerBase):
    @passthrough
    def base_action(self) -> TestResponseModel:  # type: ignore
        """Base action that returns a response model"""
        pass


class TestController(TestBaseController):
    url: str = "/test"

    async def render(self, path_param: str, query_param: int = 0) -> TestRenderModel:  # type: ignore
        """Main render method"""
        pass

    @passthrough
    def get_data(self) -> TestBaseModel:  # type: ignore
        """Get basic data"""
        pass

    @sideeffect
    def update_data(self, data: TestRequestModel) -> TestResponseModel:  # type: ignore
        """Update data with side effects"""
        pass

    @sideeffect
    async def upload_file(self, file: bytes = File(...)) -> TestResponseModel:  # type: ignore
        """File upload endpoint"""
        pass


class TestLocalGeneratorBase:
    @pytest.fixture
    def managed_path(self) -> ManagedViewPath:
        return ManagedViewPath("/test/path/file.ts")

    @pytest.fixture
    def global_root(self) -> ManagedViewPath:
        return ManagedViewPath("/test/root")

    @pytest.fixture
    def generator(self, managed_path: ManagedViewPath, global_root: ManagedViewPath):
        class ConcreteGeneratorBase(LocalGeneratorBase):
            def script(self):
                yield CodeBlock()

        return ConcreteGeneratorBase(managed_path=managed_path, global_root=global_root)

    def test_initialization(
        self,
        generator: Any,
        managed_path: ManagedViewPath,
        global_root: ManagedViewPath,
    ) -> None:
        assert generator.managed_path == managed_path
        assert generator.global_root == global_root

    def test_get_global_import_path(self, generator: Any) -> None:
        result: str = generator.get_global_import_path("test.ts")
        assert isinstance(result, str)
        assert "../" in result
        assert result.endswith("test.ts")


class TestLocalLinkGenerator:
    @pytest.fixture
    def controller_parser(self) -> ControllerParser:
        return ControllerParser()

    @pytest.fixture
    def controller_wrapper(
        self, controller_parser: ControllerParser
    ) -> ControllerWrapper:
        return controller_parser.parse_controller(TestController)

    @pytest.fixture
    def generator(
        self,
        managed_path: ManagedViewPath,
        global_root: ManagedViewPath,
        controller_wrapper: ControllerWrapper,
    ) -> Any:
        return LocalLinkGenerator(
            controller=controller_wrapper,
            managed_path=managed_path,
            global_root=global_root,
        )

    def test_script_generation(self, generator: Any) -> None:
        result: List[Any] = list(generator.script())
        assert len(result) > 0
        content: str = "\n".join(block.content for block in result)
        assert "import" in content
        assert "getLink" in content
        assert "path_param" in content
        assert "query_param" in content

    def test_get_link_implementation_with_parameters(self, generator: Any) -> None:
        impl: str = generator._get_link_implementation(generator.controller)
        assert "path_param" in impl
        assert "query_param?" in impl  # Optional parameter
        assert "/test" in impl

    def test_get_imports(self, generator: Any) -> None:
        imports: List[Any] = list(generator._get_imports(generator.controller))
        assert any("api.ts" in block.content for block in imports)
        assert any("controllers.ts" in block.content for block in imports)


class TestLocalActionGenerator:
    @pytest.fixture
    def controller_parser(self) -> ControllerParser:
        return ControllerParser()

    @pytest.fixture
    def controller_wrapper(
        self, controller_parser: ControllerParser
    ) -> ControllerWrapper:
        return controller_parser.parse_controller(TestController)

    @pytest.fixture
    def generator(
        self,
        managed_path: ManagedViewPath,
        global_root: ManagedViewPath,
        controller_wrapper: ControllerWrapper,
    ) -> Any:
        return LocalActionGenerator(
            controller=controller_wrapper,
            managed_path=managed_path,
            global_root=global_root,
        )

    def test_generate_controller_actions(self, generator: Any) -> None:
        actions: List[str] = list(
            generator._generate_controller_actions(generator.controller)
        )
        assert len(actions) == 4  # base_action, get_data, update_data, upload_file
        action_names: set[str] = {
            action
            for action in " ".join(actions).split()
            if action in ["base_action", "get_data", "update_data", "upload_file"]
        }
        assert len(action_names) == 4

    def test_get_dependent_imports(self, generator: Any) -> None:
        deps: List[str] = generator._get_dependent_imports(generator.controller)
        assert "TestRequestModel" in deps
        assert "TestResponseModel" in deps
        assert "TestBaseModel" in deps

    def test_generate_exceptions(self, generator: Any) -> None:
        imports: List[str]
        definitions: List[str]
        imports, definitions = generator._generate_exceptions(generator.controller)
        assert isinstance(imports, list)
        assert isinstance(definitions, list)


class TestLocalModelGenerator:
    @pytest.fixture
    def controller_parser(self) -> ControllerParser:
        return ControllerParser()

    @pytest.fixture
    def controller_wrapper(
        self, controller_parser: ControllerParser
    ) -> ControllerWrapper:
        return controller_parser.parse_controller(TestController)

    @pytest.fixture
    def generator(
        self,
        managed_path: ManagedViewPath,
        global_root: ManagedViewPath,
        controller_wrapper: ControllerWrapper,
    ) -> Any:
        return LocalModelGenerator(
            controller=controller_wrapper,
            managed_path=managed_path,
            global_root=global_root,
        )

    def test_script_generation(self, generator: Any) -> None:
        result: List[Any] = list(generator.script())
        assert len(result) > 0
        content: str = "\n".join(block.content for block in result)

        # Check for model exports
        assert "export type { TestBaseModel }" in content
        assert "export type { TestRequestModel }" in content
        assert "export type { TestResponseModel }" in content
        assert "export type { TestRenderModel }" in content

        # Check for enum exports
        assert "export { TestStatus }" in content


class TestLocalUseServerGenerator:
    @pytest.fixture
    def controller_parser(self) -> ControllerParser:
        return ControllerParser()

    @pytest.fixture
    def controller_wrapper(
        self, controller_parser: ControllerParser
    ) -> ControllerWrapper:
        return controller_parser.parse_controller(TestController)

    @pytest.fixture
    def generator(
        self,
        managed_path: ManagedViewPath,
        global_root: ManagedViewPath,
        controller_wrapper: ControllerWrapper,
    ) -> Any:
        return LocalUseServerGenerator(
            controller=controller_wrapper,
            managed_path=managed_path,
            global_root=global_root,
        )

    def test_script_generation_with_render(self, generator: Any) -> None:
        result: List[Any] = list(generator.script())
        content: str = "\n".join(block.content for block in result)
        assert "useServer" in content
        assert "ServerState" in content
        assert "useState" in content
        assert "applySideEffect" in content


class TestLocalIndexGenerator:
    @pytest.fixture
    def controller_parser(self) -> ControllerParser:
        return ControllerParser()

    @pytest.fixture
    def controller_wrapper(
        self, controller_parser: ControllerParser
    ) -> ControllerWrapper:
        return controller_parser.parse_controller(TestController)

    @pytest.fixture
    def generator(
        self,
        managed_path: ManagedViewPath,
        global_root: ManagedViewPath,
        controller_wrapper: ControllerWrapper,
    ) -> Any:
        return LocalIndexGenerator(
            controller=controller_wrapper,
            managed_path=managed_path,
            global_root=global_root,
        )

    def test_script_generation(self, generator: Any, tmp_path: Any) -> None:
        # Set up temporary test files
        base_path = tmp_path / "test"
        base_path.mkdir()

        (base_path / "actions.ts").write_text("export const action = () => {}")
        (base_path / "models.ts").write_text("export type Model = {}")

        # Update managed_path to use temporary directory
        generator.managed_path = ManagedViewPath(str(base_path / "index.ts"))

        result: List[Any] = list(generator.script())
        assert len(result) > 0
        content: str = "\n".join(block.content for block in result)
        assert "export * from './actions'" in content
        assert "export * from './models'" in content
