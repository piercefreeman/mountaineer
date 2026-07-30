from enum import Enum
from pathlib import Path
from typing import Any, List

import pytest
from fastapi import File
from pydantic import BaseModel

from mountaineer.actions.passthrough_dec import passthrough
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.app import AppController
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
from mountaineer.paths import ManagedViewPath
from mountaineer.render import RenderBase


# Test Models and Enums
class ExampleStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class ExampleBaseModel(BaseModel):
    name: str
    status: ExampleStatus


class ExampleRequestModel(BaseModel):
    query: str
    limit: int = 10


class ExampleResponseModel(BaseModel):
    results: List[str]
    total: int


class ExampleRenderModel(RenderBase):
    title: str
    items: List[ExampleBaseModel]


# Test Controllers
class ExampleBaseController(ControllerBase):
    @passthrough
    def base_action(self) -> ExampleResponseModel:  # type: ignore
        """Base action that returns a response model"""
        pass


class ExampleController(ExampleBaseController):
    url = "/test"
    view_path = "/test.tsx"

    async def render(  # type: ignore
        self,
        path_param: str,
        query_param: int = 0,
        enum_param: ExampleStatus = ExampleStatus.ACTIVE,
    ) -> ExampleRenderModel:  # type: ignore
        """Main render method"""
        pass

    @passthrough
    def get_data(self) -> ExampleBaseModel:  # type: ignore
        """Get basic data"""
        pass

    @sideeffect
    def update_data(self, data: ExampleRequestModel) -> ExampleResponseModel:  # type: ignore
        """Update data with side effects"""
        pass

    @sideeffect
    async def upload_file(self, file: bytes = File(...)) -> ExampleResponseModel:  # type: ignore
        """File upload endpoint"""
        pass


@pytest.fixture
def managed_path(tmp_path: Path) -> ManagedViewPath:
    controller_path = tmp_path / "test_controller"
    controller_path.mkdir()
    return ManagedViewPath(controller_path)


@pytest.fixture
def global_root(tmp_path: Path) -> ManagedViewPath:
    return ManagedViewPath(tmp_path)


@pytest.fixture
def controller_parser() -> ControllerParser:
    return ControllerParser()


@pytest.fixture
def controller_wrapper(controller_parser: ControllerParser) -> ControllerWrapper:
    app_controller = AppController(view_root=Path())
    app_controller.register(ExampleController())

    return controller_parser.parse_controller(ExampleController)


@pytest.fixture
def base_generator(
    managed_path: ManagedViewPath, global_root: ManagedViewPath
) -> LocalGeneratorBase:
    class ConcreteGeneratorBase(LocalGeneratorBase):
        def script(self):
            yield CodeBlock()

    return ConcreteGeneratorBase(managed_path=managed_path, global_root=global_root)


@pytest.fixture
def link_generator(
    managed_path: ManagedViewPath,
    global_root: ManagedViewPath,
    controller_wrapper: ControllerWrapper,
) -> LocalLinkGenerator:
    return LocalLinkGenerator(
        controller=controller_wrapper,
        managed_path=managed_path,
        global_root=global_root,
    )


@pytest.fixture
def action_generator(
    managed_path: ManagedViewPath,
    global_root: ManagedViewPath,
    controller_wrapper: ControllerWrapper,
) -> LocalActionGenerator:
    return LocalActionGenerator(
        controller=controller_wrapper,
        managed_path=managed_path,
        global_root=global_root,
    )


@pytest.fixture
def model_generator(
    managed_path: ManagedViewPath,
    global_root: ManagedViewPath,
    controller_wrapper: ControllerWrapper,
) -> LocalModelGenerator:
    return LocalModelGenerator(
        controller=controller_wrapper,
        managed_path=managed_path,
        global_root=global_root,
    )


@pytest.fixture
def server_generator(
    managed_path: ManagedViewPath,
    global_root: ManagedViewPath,
    controller_wrapper: ControllerWrapper,
) -> LocalUseServerGenerator:
    return LocalUseServerGenerator(
        controller=controller_wrapper,
        managed_path=managed_path,
        global_root=global_root,
    )


@pytest.fixture
def index_generator(
    managed_path: ManagedViewPath,
    global_root: ManagedViewPath,
    controller_wrapper: ControllerWrapper,
) -> LocalIndexGenerator:
    return LocalIndexGenerator(
        controller=controller_wrapper,
        managed_path=managed_path,
        global_root=global_root,
    )


class TestLocalGeneratorBase:
    def test_get_global_import_path(self, base_generator: LocalGeneratorBase) -> None:
        result: str = base_generator.get_global_import_path("test.ts")
        assert isinstance(result, str)
        assert "../" in result
        assert result.endswith("test")


class TestLocalLinkGenerator:
    def test_script_generation(self, link_generator: LocalLinkGenerator) -> None:
        result = list(link_generator.script())
        assert len(result) > 0
        content = "\n".join(block.content for block in result)
        assert "import" in content
        assert "getLink" in content
        assert "path_param" in content
        assert "query_param" in content
        assert "enum_param" in content

    def test_get_link_implementation_with_parameters(
        self, link_generator: LocalLinkGenerator
    ) -> None:
        impl = link_generator._get_link_implementation(link_generator.controller)
        assert "path_param" in impl
        assert "query_param?" in impl  # Optional parameter
        assert "enum_param?" in impl  # Optional parameter
        assert "/test" in impl

    def test_get_imports(self, link_generator: LocalLinkGenerator) -> None:
        imports = list(link_generator._get_imports(link_generator.controller))
        assert any("../api" in block.content for block in imports)
        assert any("../controllers" in block.content for block in imports)


class TestLocalActionGenerator:
    def test_generate_controller_actions(
        self, action_generator: LocalActionGenerator
    ) -> None:
        actions = list(
            action_generator._generate_controller_actions(action_generator.controller)
        )
        assert len(actions) == 4  # base_action, get_data, update_data, upload_file
        action_names: set[str] = {
            action
            for action in " ".join(actions).split()
            if action in ["base_action", "get_data", "update_data", "upload_file"]
        }
        assert len(action_names) == 4

    def test_get_dependent_imports(
        self, action_generator: LocalActionGenerator
    ) -> None:
        deps = action_generator._get_dependent_imports(action_generator.controller)

        # Response wrapped models
        assert deps == {
            "BaseActionResponseWrapped",
            "ExampleRequestModel",
            "GetDataResponseWrapped",
            "UpdateDataResponseWrapped",
            "UploadFileForm",
            "UploadFileResponseWrapped",
        }

    def test_exception_payload_imports_are_type_only(
        self, action_generator: LocalActionGenerator
    ) -> None:
        content = "\n".join(block.content for block in action_generator.script())

        assert "import { __request, FetchErrorBase }" in content
        assert (
            "import type { RequestValidationError as RequestValidationErrorBase }"
            in content
        )
        assert (
            "import { RequestValidationError as RequestValidationErrorBase }"
            not in content
        )
        assert (
            "export class RequestValidationError extends "
            "FetchErrorBase<RequestValidationErrorBase>"
        ) in content


class TestLocalModelGenerator:
    def test_script_generation(self, model_generator: LocalModelGenerator) -> None:
        result: List[Any] = list(model_generator.script())
        assert len(result) > 0
        content: str = "\n".join(block.content for block in result)

        # Check for model exports
        assert "export type { ExampleRequestModel as ExampleRequestModel }" in content
        assert "export type { ExampleResponseModel as ExampleResponseModel }" in content
        assert "export type { ExampleRenderModel as ExampleRenderModel }" in content

        # Check for enum exports
        assert "export { ExampleStatus as ExampleStatus }" in content


class TestLocalUseServerGenerator:
    def test_script_generation_with_render(
        self, server_generator: LocalUseServerGenerator
    ) -> None:
        result: List[Any] = list(server_generator.script())
        content: str = "\n".join(block.content for block in result)
        assert "useServer" in content
        assert "ServerState" in content
        assert "useCallback" in content
        assert "useMemo" in content
        assert "useState" in content
        assert "applySideEffect" in content
        assert "const setControllerState = useCallback" in content
        assert "const update_dataWithSideEffect = useMemo(" in content
        assert "const upload_fileWithSideEffect = useMemo(" in content
        assert "update_data: update_dataWithSideEffect" in content
        assert "upload_file: upload_fileWithSideEffect" in content
        assert "return useMemo((): ServerState => ({" in content


class TestLocalIndexGenerator:
    def test_script_generation(
        self, index_generator: LocalIndexGenerator, managed_path: ManagedViewPath
    ) -> None:
        (managed_path.parent / "actions.ts").write_text(
            "export const action = () => {}"
        )
        (managed_path.parent / "models.ts").write_text("export type Model = {}")

        result: List[Any] = list(index_generator.script())
        assert len(result) > 0
        content: str = "\n".join(block.content for block in result)
        assert "export * from './actions'" in content
        assert "export * from './models'" in content
