from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import AsyncIterator, Generic, Optional, TypeVar

import pytest
from fastapi import File, Form, UploadFile
from pydantic import BaseModel, ConfigDict, field_validator

from mountaineer.__tests__.client_builder.interface_builders.common import (
    create_field_wrapper,
    create_model_wrapper,
)
from mountaineer.actions.fields import FunctionActionType
from mountaineer.actions.passthrough_dec import passthrough
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.app import AppController
from mountaineer.client_builder.parser import (
    ActionWrapper,
    ControllerParser,
    ControllerWrapper,
    EnumWrapper,
    FieldWrapper,
    ModelWrapper,
)
from mountaineer.client_builder.types import ListOf
from mountaineer.controller import ControllerBase
from mountaineer.render import RenderBase


# Create a simple response model for testing
class StandardResponse(BaseModel):
    message: str


# Type variables for generic tests
T = TypeVar("T")
S = TypeVar("S")


# Core test enum
class ExampleEnum(Enum):
    A = "a"
    B = "b"
    C = "c"


# Core test models
class ExampleModelBase(BaseModel):
    string_field: str
    int_field: int
    enum_field: ExampleEnum

    @field_validator("string_field")
    def validate_string(cls, v):
        if len(v) < 3:
            raise ValueError("String too short")
        return v.upper()


# Generic test models
class GenericTestModel(BaseModel, Generic[T]):
    value: T
    metadata: str


class MultiGenericTestModel(GenericTestModel[T], Generic[T, S]):
    second_value: S


class NestedGenericTestModel(BaseModel, Generic[T]):
    wrapper: GenericTestModel[T]
    list_of: list[GenericTestModel[T]]


# Inheritance test models
class BaseInheritanceModel(ExampleModelBase):
    base_field: str


class LeftInheritanceModel(BaseInheritanceModel):
    left_field: int


class RightInheritanceModel(BaseInheritanceModel):
    right_field: float


class DiamondInheritanceModel(LeftInheritanceModel, RightInheritanceModel):
    final_field: bool


# Circular reference model
class CircularModel(BaseModel):
    name: str
    parent: Optional["CircularModel"] = None


CircularModel.model_rebuild()


# Controller response models
class ControllerResponse(BaseModel):
    message: str
    timestamp: datetime


class FileUploadResponse(BaseModel):
    filename: str
    size: int


class RenderResponse(RenderBase):
    data: ExampleModelBase
    count: int = 0


# Controller hierarchy
class BaseExampleController:
    @passthrough
    def base_action(self) -> ControllerResponse:  # type: ignore
        pass


class ExampleController(ControllerBase, BaseExampleController):
    url = "/test/{path_param}"
    view_path = "/test.tsx"

    async def render(self, path_param: str, query_param: int = 0) -> RenderResponse:  # type: ignore
        pass

    @passthrough
    def get_data(self) -> ExampleModelBase:  # type: ignore
        pass

    @sideeffect
    def update_form(  # type: ignore
        self, name: str = Form(...), size: int = Form(...)
    ) -> FileUploadResponse:  # type: ignore
        pass

    @sideeffect
    def upload_file(self, file: UploadFile = File(...)) -> FileUploadResponse:  # type: ignore
        pass


class SpecialTypesController(ControllerBase):
    url = "/test2"
    view_path = "/test2.tsx"

    @passthrough(raw_response=True)  # type: ignore
    async def raw_action(self) -> ExampleModelBase:  # type: ignore
        pass

    @passthrough
    async def stream_action(self) -> AsyncIterator[ExampleModelBase]:
        yield ExampleModelBase(
            string_field="test", int_field=1, enum_field=ExampleEnum.A
        )


# Tests
class TestControllerParser:
    @pytest.fixture
    def parser(self):
        parser = ControllerParser()
        app_controller = AppController(view_root=Path())
        app_controller.register(ExampleController())
        return parser

    @pytest.fixture
    def base_model_wrapper(self, parser: ControllerParser):
        return parser._parse_model(ExampleModelBase)

    @pytest.fixture
    def test_controller_wrapper(self, parser: ControllerParser):
        return parser.parse_controller(ExampleController)

    def test_parse_enum(self, parser: ControllerParser):
        wrapper = parser._parse_enum(ExampleEnum)
        assert isinstance(wrapper, EnumWrapper)
        assert wrapper.enum == ExampleEnum
        assert wrapper.name.raw_name == "ExampleEnum"

    def test_parse_base_model(self, parser: ControllerParser):
        wrapper = parser._parse_model(ExampleModelBase)
        assert isinstance(wrapper, ModelWrapper)
        assert wrapper.model == ExampleModelBase
        assert len(wrapper.value_models) == 3
        assert wrapper.superclasses == []

    def test_parse_generic_model(self, parser: ControllerParser):
        wrapper = parser._parse_model(GenericTestModel[str])
        assert isinstance(wrapper, ModelWrapper)
        assert wrapper.model == GenericTestModel[str]
        assert len(wrapper.value_models) == 2

    def test_parse_nested_generic_model(self, parser: ControllerParser):
        wrapper = parser._parse_model(NestedGenericTestModel[int])
        assert isinstance(wrapper, ModelWrapper)
        assert len(wrapper.value_models) == 2
        # Verify nested models were parsed
        assert any(isinstance(f.value, ModelWrapper) for f in wrapper.value_models)

    def test_parse_circular_model(self, parser: ControllerParser):
        wrapper = parser._parse_model(CircularModel)
        assert isinstance(wrapper, ModelWrapper)
        assert len(wrapper.value_models) == 2
        assert any(f.name == "parent" for f in wrapper.value_models)
        assert len(parser.parsed_self_references) == 1

    def test_parse_controller_inheritance(self, parser: ControllerParser):
        wrapper = parser.parse_controller(ExampleController)
        assert isinstance(wrapper, ControllerWrapper)
        assert len(wrapper.superclasses) == 1
        assert wrapper.superclasses[0].controller == BaseExampleController

    def test_parse_controller_actions(self, parser: ControllerParser):
        wrapper = parser.parse_controller(ExampleController)
        assert len(wrapper.actions) == 3

        # Actions explicitly tied to this class
        known_passthrough = {"get_data"}
        known_sideeffect = {"update_form", "upload_file"}

        # Verify different action types
        assert {
            a.name
            for a in wrapper.actions.values()
            if a.action_type == FunctionActionType.PASSTHROUGH
        } == known_passthrough
        assert {
            a.name
            for a in wrapper.actions.values()
            if a.action_type == FunctionActionType.SIDEEFFECT
        } == known_sideeffect

    def test_parse_render_method(self, parser: ControllerParser):
        wrapper = parser.parse_controller(ExampleController)
        assert wrapper.render is not None
        assert len(wrapper.paths) == 1
        assert len(wrapper.queries) == 1

    def test_parse_form_action(self, parser: ControllerParser):
        wrapper = parser.parse_controller(ExampleController)
        action = wrapper.actions.get("update_form")
        assert action is not None
        assert action.request_body is not None
        assert action.request_body.body_type == "application/x-www-form-urlencoded"

    def test_parse_file_upload_action(self, parser: ControllerParser):
        wrapper = parser.parse_controller(ExampleController)
        action = wrapper.actions.get("upload_file")
        assert action is not None
        assert action.request_body is not None
        assert action.request_body.body_type == "multipart/form-data"

    def test_parse_raw_response(self, parser: ControllerParser):
        wrapper = parser.parse_controller(SpecialTypesController)
        action = wrapper.actions.get("raw_action")
        assert action is not None
        assert action.is_raw_response

    def test_parse_server_side_renderer(self, parser: ControllerParser):
        wrapper = parser.parse_controller(SpecialTypesController)
        action = wrapper.actions.get("stream_action")
        assert action is not None
        assert action.is_streaming_response

    def test_parse_multiple_response_types(self, parser: ControllerParser):
        """
        Test that one action that's shared by multiple children will have
        a response type that includes all possible response models.

        """

        class ResponseA(RenderBase):
            pass

        class ResponseB(RenderBase):
            pass

        class MultiResponseParent(ControllerBase):
            @sideeffect
            def multi_action(self) -> None:
                pass

        class ResponseAController(MultiResponseParent):
            url = "/response_a"
            view_path = "/response_a.tsx"

            async def render(self) -> ResponseA:  # type: ignore
                pass

        class ResponseBController(MultiResponseParent):
            url = "/response_b"
            view_path = "/response_b.tsx"

            async def render(self) -> ResponseB:  # type: ignore
                pass

        app_controller = AppController(view_root=Path())
        app_controller.register(ResponseAController())
        app_controller.register(ResponseBController())

        wrapper: ControllerWrapper = parser.parse_controller(MultiResponseParent)
        action = wrapper.actions["multi_action"]

        a_response = action.response_bodies[ResponseAController]
        b_response = action.response_bodies[ResponseBController]

        assert a_response
        assert b_response

        response_a_sideeffect = next(
            field for field in a_response.value_models if field.name == "sideeffect"
        )
        response_b_sideeffect = next(
            field for field in b_response.value_models if field.name == "sideeffect"
        )

        assert isinstance(response_a_sideeffect.value, ModelWrapper)
        assert isinstance(response_b_sideeffect.value, ModelWrapper)

        assert response_a_sideeffect.value.model == ResponseA
        assert response_b_sideeffect.value.model == ResponseB


class TestInheritanceHandling:
    @pytest.fixture
    def parser(self):
        return ControllerParser()

    def test_basic_inheritance(self, parser: ControllerParser):
        wrapper = parser._parse_model(BaseInheritanceModel)
        assert len(wrapper.superclasses) == 1
        assert wrapper.superclasses[0].model == ExampleModelBase

    def test_diamond_inheritance(self, parser: ControllerParser):
        wrapper = parser._parse_model(DiamondInheritanceModel)
        assert len([sc.name.global_name for sc in wrapper.superclasses]) == 2
        superclass_models = {s.model for s in wrapper.superclasses}
        assert LeftInheritanceModel in superclass_models
        assert RightInheritanceModel in superclass_models


class TestGenericHandling:
    @pytest.fixture
    def parser(self):
        return ControllerParser()

    def test_basic_generic(self, parser: ControllerParser):
        wrapper = parser._parse_model(GenericTestModel[str])
        assert len(wrapper.value_models) == 2
        assert wrapper.value_models[0].value == str

    def test_multi_generic(self, parser: ControllerParser):
        wrapper = parser._parse_model(MultiGenericTestModel[str, int])
        assert len(wrapper.value_models) == 1
        assert any(
            f.name == "second_value" and f.value == int for f in wrapper.value_models
        )

    def test_nested_generic_resolution(self, parser: ControllerParser):
        wrapper = parser._parse_model(NestedGenericTestModel[str])
        assert len(wrapper.value_models) == 2
        list_field = next(f for f in wrapper.value_models if f.name == "list_of")
        assert isinstance(list_field.value, ListOf)
        assert isinstance(list_field.value.children[0], ModelWrapper)
        assert "GenericTestModel[str]" in str(list_field.value.children[0].model)


class TestControllerWrapperFeatures:
    @pytest.fixture
    def parser(self):
        parser = ControllerParser()
        app_controller = AppController(view_root=Path())
        app_controller.register(ExampleController())
        return parser

    def test_all_actions_collection(self, parser: ControllerParser):
        wrapper = parser.parse_controller(ExampleController)
        action_names = {action.name for action in wrapper.all_actions}
        assert action_names == {"base_action", "get_data", "update_form", "upload_file"}

    @pytest.mark.parametrize(
        "include_superclasses, expected_models",
        [
            (False, {"ExampleModelBase", "FileUploadResponse", "RenderResponse"}),
            (
                True,
                {
                    "ExampleModelBase",
                    "ControllerResponse",
                    "FileUploadResponse",
                    "RenderResponse",
                },
            ),
        ],
    )
    def test_embedded_types_collection(
        self,
        parser: ControllerParser,
        include_superclasses: bool,
        expected_models: set[str],
    ):
        wrapper = parser.parse_controller(ExampleController)
        embedded = ControllerWrapper.get_all_embedded_types(
            [wrapper], include_superclasses=include_superclasses
        )

        model_names = {m.model.__name__ for m in embedded.models}
        assert model_names.intersection(expected_models) == expected_models

    def test_embedded_controllers(self, parser: ControllerParser):
        wrapper = parser.parse_controller(ExampleController)
        controllers = ControllerWrapper.get_all_embedded_controllers([wrapper])

        controller_types = {c.controller for c in controllers}
        assert controller_types == {ExampleController, BaseExampleController}


class TestIsolatedModelCreation:
    @pytest.fixture
    def parser(self):
        return ControllerParser()

    def test_standard_model_isolation(self, parser: ControllerParser):
        class ParentModel(BaseModel):
            parent_field: str
            shared_field: int = 0

        class ChildModel(ParentModel):
            child_field: str
            shared_field: int = 1  # Override parent field

        isolated = parser._create_isolated_model(ChildModel)

        # Should only include fields directly defined in ChildModel
        assert set(isolated.model_fields.keys()) == {"child_field", "shared_field"}
        assert "parent_field" not in isolated.model_fields

        # Check that field types are preserved
        assert isolated.model_fields["child_field"].annotation == str
        assert isolated.model_fields["shared_field"].annotation == int

    def test_nested_inheritance_isolation(self, parser: ControllerParser):
        class GrandparentModel(BaseModel):
            grandparent_field: str

        class ParentModel(GrandparentModel):
            parent_field: int

        class ChildModel(ParentModel):
            child_field: bool

        isolated = parser._create_isolated_model(ChildModel)

        # Should only include fields from ChildModel
        assert set(isolated.model_fields.keys()) == {"child_field"}
        assert "parent_field" not in isolated.model_fields
        assert "grandparent_field" not in isolated.model_fields

    def test_generic_model_isolation(self, parser: ControllerParser):
        class GenericParent(BaseModel, Generic[T]):
            parent_field: T
            shared_field: str = "parent"

        class GenericChild(GenericParent[int]):
            child_field: str
            shared_field: str = "child"  # Override parent field

        isolated = parser._create_isolated_model(GenericChild)

        # Should only include fields defined directly in GenericChild
        assert set(isolated.model_fields.keys()) == {"child_field", "shared_field"}
        assert "parent_field" not in isolated.model_fields

        # Verify field types are correctly resolved
        assert isolated.model_fields["child_field"].annotation == str
        assert isolated.model_fields["shared_field"].annotation == str

    def test_multi_generic_model_isolation(self, parser: ControllerParser):
        class MultiGenericParent(BaseModel, Generic[T, S]):
            field_t: T
            field_s: S

        class MultiGenericChild(MultiGenericParent[str, int]):
            child_field: bool

        isolated = parser._create_isolated_model(MultiGenericChild)

        # Should only include fields defined in child
        assert set(isolated.model_fields.keys()) == {"child_field"}
        assert "field_t" not in isolated.model_fields
        assert "field_s" not in isolated.model_fields

        # Verify field type
        assert isolated.model_fields["child_field"].annotation == bool

    def test_model_config_preservation(self, parser: ControllerParser):
        class CustomModel(BaseModel):
            field: str

            model_config = ConfigDict(
                str_strip_whitespace=True,
                frozen=True,
            )

        isolated = parser._create_isolated_model(CustomModel)

        # Check that model configuration is preserved
        assert isolated.model_config["str_strip_whitespace"] is True  # type: ignore
        assert isolated.model_config["frozen"] is True  # type: ignore

    def test_empty_model_isolation(self, parser: ControllerParser):
        class EmptyParent(BaseModel):
            parent_field: str

        class EmptyChild(EmptyParent):
            pass  # No direct fields

        isolated = parser._create_isolated_model(EmptyChild)

        # Should have no fields since child defines none directly
        assert not isolated.model_fields


class TestActionWrapper:
    @pytest.fixture
    def parser(self):
        parser = ControllerParser()
        app_controller = AppController(view_root=Path())
        app_controller.register(ExampleController())
        return parser

    @pytest.mark.parametrize(
        "params, headers, request_body, expected_has_required",
        [
            # Base cases - no headers or request body
            ([], [], None, False),
            ([create_field_wrapper("optional_param", str, False)], [], None, False),
            ([create_field_wrapper("required_param", str, True)], [], None, True),
            # Headers only
            ([], [create_field_wrapper("optional_header", str, False)], None, False),
            ([], [create_field_wrapper("required_header", str, True)], None, True),
            (
                [],
                [
                    create_field_wrapper("required_header", str, True),
                    create_field_wrapper("optional_header", str, False),
                ],
                None,
                True,
            ),
            # Request body only
            (
                [],
                [],
                create_model_wrapper(ExampleModelBase, "ExampleModelBase"),
                True,  # Request body is always required
            ),
            # Combination of params, headers, and request body
            (
                [create_field_wrapper("optional_param", str, False)],
                [create_field_wrapper("optional_header", str, False)],
                None,
                False,
            ),
            (
                [create_field_wrapper("required_param", str, True)],
                [create_field_wrapper("optional_header", str, False)],
                None,
                True,
            ),
            (
                [create_field_wrapper("optional_param", str, False)],
                [create_field_wrapper("required_header", str, True)],
                None,
                True,
            ),
            (
                [create_field_wrapper("optional_param", str, False)],
                [create_field_wrapper("optional_header", str, False)],
                create_model_wrapper(ExampleModelBase, "ExampleModelBase"),
                True,  # Request body makes it required
            ),
            (
                [create_field_wrapper("required_param", str, True)],
                [create_field_wrapper("required_header", str, True)],
                create_model_wrapper(ExampleModelBase, "ExampleModelBase"),
                True,
            ),
        ],
    )
    def test_has_required_params(
        self,
        params: list[FieldWrapper],
        headers: list[FieldWrapper],
        request_body: Optional[ModelWrapper],
        expected_has_required: bool,
    ):
        action = ActionWrapper(
            name="test_action",
            module_name="test_module",
            action_type=FunctionActionType.PASSTHROUGH,
            params=params,
            headers=headers,
            request_body=request_body,
            response_bodies={
                ControllerBase: create_model_wrapper(
                    StandardResponse, "StandardResponse"
                )
            },
            exceptions=[],
            is_raw_response=False,
            is_streaming_response=False,
            controller_to_url={ControllerBase: "/api/test"},
        )

        assert action.has_required_params() == expected_has_required
