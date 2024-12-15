from enum import Enum
from typing import Generic, Optional, Type, TypeVar, cast

import pytest
from pydantic import BaseModel

from mountaineer.client_builder.aliases import AliasManager
from mountaineer.client_builder.parser import (
    ControllerParser,
    ControllerWrapper,
    EnumWrapper,
    ModelWrapper,
    SelfReference,
    WrapperName,
)
from mountaineer.controller import ControllerBase

T = TypeVar("T")


class TestAliasManager:
    @pytest.fixture
    def parser(self) -> ControllerParser:
        return ControllerParser()

    @pytest.fixture
    def alias_manager(self) -> AliasManager:
        return AliasManager()

    def test_basic_name_normalization(
        self, parser: ControllerParser, alias_manager: AliasManager
    ) -> None:
        class TestModel(BaseModel):
            field: str

        wrapper: ModelWrapper = ModelWrapper(
            name=WrapperName(TestModel.__name__),
            module_name="test.module",
            model=TestModel,
            isolated_model=TestModel,
            superclasses=[],
            value_models=[],
        )
        parser.parsed_models[TestModel] = wrapper

        alias_manager.assign_global_names(parser)
        assert wrapper.name.global_name == "TestModel"
        assert wrapper.name.raw_name == "TestModel"

    def test_global_model_conflict_resolution(
        self, parser: ControllerParser, alias_manager: AliasManager
    ) -> None:
        class User(BaseModel):
            name: str

        class User2(BaseModel):
            email: str

        User2.__name__ = "User"  # Force name conflict
        User2.__module__ = "auth.models"

        wrapper1: ModelWrapper = ModelWrapper(
            name=WrapperName(User.__name__),
            module_name="users.models",
            model=User,
            isolated_model=User,
            superclasses=[],
            value_models=[],
        )

        wrapper2: ModelWrapper = ModelWrapper(
            name=WrapperName(User2.__name__),
            module_name="auth.models",
            model=User2,
            isolated_model=User2,
            superclasses=[],
            value_models=[],
        )

        parser.parsed_models[User] = wrapper1
        parser.parsed_models[User2] = wrapper2

        alias_manager.assign_global_names(parser)

        assert wrapper1.name.global_name == "UsersModels_User"
        assert wrapper2.name.global_name == "AuthModels_User"

    def test_cross_type_conflict_resolution(
        self, parser: ControllerParser, alias_manager: AliasManager
    ) -> None:
        class Status1(BaseModel):
            code: int

        class Status2(Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        Status1.__name__ = "Status"
        Status2.__name__ = "Status"

        model_wrapper: ModelWrapper = ModelWrapper(
            name=WrapperName("Status"),
            module_name="models.status",
            model=Status1,
            isolated_model=Status1,
            superclasses=[],
            value_models=[],
        )

        enum_wrapper: EnumWrapper = EnumWrapper(
            name=WrapperName("Status"), module_name="enums.status", enum=Status2
        )

        parser.parsed_models[Status1] = model_wrapper
        parser.parsed_enums[Status2] = enum_wrapper

        alias_manager.assign_global_names(parser)

        assert model_wrapper.name.global_name == "ModelsStatus_Status"
        assert enum_wrapper.name.global_name == "EnumsStatus_Status"

    def test_self_reference_updating(
        self, parser: ControllerParser, alias_manager: AliasManager
    ) -> None:
        class Node(BaseModel):
            value: str
            parent: Optional["Node"] = None

        class Node2(BaseModel):
            value: str
            parent: Optional[Node] = None

        wrapper: ModelWrapper = ModelWrapper(
            name=WrapperName("Node"),
            module_name="tree.models",
            model=Node,
            isolated_model=Node,
            superclasses=[],
            value_models=[],
        )

        # We just need to insert two of the same value so the duplicate detection
        # is triggered, their keys don't matter
        parser.parsed_models[Node] = wrapper
        parser.parsed_models[Node2] = wrapper
        parser.parsed_self_references.append(SelfReference(name="Node", model=Node))

        alias_manager.assign_global_names(parser)

        assert wrapper.name.global_name == "TreeModels_Node"
        assert parser.parsed_self_references[0].name == "TreeModels_Node"

    def test_local_name_resolution(
        self, parser: ControllerParser, alias_manager: AliasManager
    ) -> None:
        class StatusEnum(Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        class UserModel(BaseModel):
            name: str
            status: StatusEnum

        class TestController(ControllerBase):
            url: str = "/test"

        controller_wrapper: ControllerWrapper = ControllerWrapper(
            name=WrapperName("TestController"),
            module_name="controllers",
            entrypoint_url="/test",
            controller=TestController,
            superclasses=[],
            queries=[],
            paths=[],
            render=None,
            actions={},
        )

        model_wrapper: ModelWrapper = ModelWrapper(
            name=WrapperName("UserModel"),
            module_name="models",
            model=UserModel,
            isolated_model=UserModel,
            superclasses=[],
            value_models=[],
        )

        enum_wrapper: EnumWrapper = EnumWrapper(
            name=WrapperName("StatusEnum"), module_name="enums", enum=StatusEnum
        )

        parser.parsed_controllers[TestController] = controller_wrapper
        parser.parsed_models[UserModel] = model_wrapper
        parser.parsed_enums[StatusEnum] = enum_wrapper

        alias_manager.assign_local_names(parser)

        assert model_wrapper.name.local_name == "UserModel"
        assert enum_wrapper.name.local_name == "StatusEnum"

    def test_generic_model_naming(
        self, parser: ControllerParser, alias_manager: AliasManager
    ) -> None:
        class Container(BaseModel, Generic[T]):
            value: T

        string_generic = cast(Type[BaseModel], Container[str])
        int_generic = cast(Type[BaseModel], Container[int])

        wrappers = {
            cls: ModelWrapper(
                name=WrapperName(cls.__name__),
                module_name=cls.__module__,
                model=cls,
                isolated_model=cls,
                superclasses=[],
                value_models=[],
            )
            for cls in [string_generic, int_generic]
        }

        for cls, wrapper in wrappers.items():
            parser.parsed_models[cls] = wrapper

        alias_manager.assign_global_names(parser)

        assert wrappers[string_generic].name.global_name == "ContainerStr"
        assert wrappers[int_generic].name.global_name == "ContainerInt"

    @pytest.mark.parametrize(
        "original_name, module, expected",
        [
            ("A", "test.module", "TestModule_A"),
            ("with_underscore", "test.module", "TestModule_WithUnderscore"),
            ("MyClass", "a.b.c.d", "ABCD_MyClass"),
            ("123Invalid", "test", "Test_123Invalid"),
            ("With Space", "test", "Test_WithSpace"),
        ],
    )
    def test_edge_cases(
        self,
        parser: ControllerParser,
        alias_manager: AliasManager,
        original_name: str,
        module: str,
        expected: str,
    ) -> None:
        class DynamicModel(BaseModel):
            field: str

        class OtherModel(BaseModel):
            field: str

        wrapper: ModelWrapper = ModelWrapper(
            name=WrapperName(original_name),
            module_name=module,
            model=DynamicModel,
            isolated_model=DynamicModel,
            superclasses=[],
            value_models=[],
        )

        parser.parsed_models[DynamicModel] = wrapper
        parser.parsed_models[OtherModel] = wrapper
        alias_manager.assign_global_names(parser)
        assert wrapper.name.global_name == expected

    @pytest.mark.parametrize(
        "module_path,expected_prefix",
        [
            ("users", "Users"),
            ("auth.models", "AuthModels"),
            ("api.v1.users.models", "ApiV1UsersModels"),
            ("my_app.user_models", "MyAppUserModels"),
            ("a.b.c", "ABC"),
            ("", ""),
            ("with.multiple.dots.at.end...", "WithMultipleDotsAtEnd"),
            ("___internal.models", "InternalModels"),
            ("api.v2", "ApiV2"),
            (
                "complex_name.with_underscores.and_numbers2",
                "ComplexNameWithUnderscoresAndNumbers2",
            ),
        ],
    )
    def test_typescript_prefix_from_module(
        self, alias_manager: AliasManager, module_path: str, expected_prefix: str
    ) -> None:
        """Test the module prefix formatting for various module path patterns"""
        result: str = alias_manager._typescript_prefix_from_module(module_path)
        assert result == expected_prefix
