from typing import AsyncIterator, Iterator, Optional

import pytest
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from mountaineer.actions.fields import (
    FunctionActionType,
    FunctionMetadata,
    ResponseModelType,
    annotation_is_metadata,
    extract_response_model_from_signature,
    fuse_metadata_to_response_typehint,
)
from mountaineer.controller import ControllerBase
from mountaineer.render import Metadata, RenderBase


class ExampleRenderModel(RenderBase):
    render_value_a: str
    render_value_b: int


class ExamplePassthroughModel(BaseModel):
    passthrough_value_a: str
    passthrough_value_b: int


class ExampleController(ControllerBase):
    async def render(self) -> None:
        pass


def basic_compare_model_fields(
    actual: dict[str, FieldInfo],
    expected: dict[str, FieldInfo],
):
    """
    FieldInfo objects can't be compared with native Python comparitors.
    """
    assert actual.keys() == expected.keys()
    for key in actual:
        assert actual[key].annotation == expected[key].annotation
        assert actual[key].default == expected[key].default
        assert actual[key].alias == expected[key].alias
        assert actual[key].is_required() == expected[key].is_required()


@pytest.mark.parametrize(
    "metadata, render_model, expected_model_name, expected_sideeffect_fields, expected_passthrough_fields",
    [
        # Case 1: Basic passthrough only
        (
            FunctionMetadata(
                action_type=FunctionActionType.PASSTHROUGH,
                function_name="example_function",
                passthrough_model=ExamplePassthroughModel,
            ),
            ExampleRenderModel,
            "ExampleFunctionResponseWrapped",
            None,
            {
                "passthrough_value_a": FieldInfo.from_annotation(annotation=str),
                "passthrough_value_b": FieldInfo.from_annotation(annotation=int),
            },
        ),
        # Case 2: Full sideeffect model (no reload states)
        (
            FunctionMetadata(
                action_type=FunctionActionType.SIDEEFFECT,
                function_name="example_function",
            ),
            ExampleRenderModel,
            "ExampleFunctionResponseWrapped",
            {
                "render_value_a": FieldInfo.from_annotation(annotation=str),
                "render_value_b": FieldInfo.from_annotation(annotation=int),
                "metadata": FieldInfo(annotation=Metadata | None, default=None),  # type: ignore
            },
            None,
        ),
        # Case 3: Sideeffect with reload states
        (
            FunctionMetadata(
                action_type=FunctionActionType.SIDEEFFECT,
                function_name="example_function",
                reload_states=tuple([ExampleRenderModel.render_value_a]),  # type: ignore
            ),
            ExampleRenderModel,
            "ExampleFunctionResponseWrapped",
            {
                "render_value_a": FieldInfo.from_annotation(annotation=str),
            },
            None,
        ),
        # Case 4: Combined passthrough and sideeffect
        (
            FunctionMetadata(
                action_type=FunctionActionType.SIDEEFFECT,
                function_name="example_function",
                passthrough_model=ExamplePassthroughModel,
                reload_states=tuple([ExampleRenderModel.render_value_a]),  # type: ignore
            ),
            ExampleRenderModel,
            "ExampleFunctionResponseWrapped",
            {
                "render_value_a": FieldInfo.from_annotation(annotation=str),
            },
            {
                "passthrough_value_a": FieldInfo.from_annotation(annotation=str),
                "passthrough_value_b": FieldInfo.from_annotation(annotation=int),
            },
        ),
    ],
)
def test_fuse_metadata_to_response_typehint(
    metadata: FunctionMetadata,
    render_model: type[RenderBase],
    expected_model_name: str,
    expected_sideeffect_fields: dict[str, FieldInfo] | None,
    expected_passthrough_fields: dict[str, FieldInfo] | None,
):
    sample_controller = ExampleController()
    result_model = fuse_metadata_to_response_typehint(
        metadata, sample_controller, render_model
    )

    # Verify model name
    assert result_model.__name__ == expected_model_name

    # Check sideeffect fields if expected
    if expected_sideeffect_fields:
        assert "sideeffect" in result_model.model_fields
        assert result_model.model_fields["sideeffect"].annotation
        basic_compare_model_fields(
            result_model.model_fields["sideeffect"].annotation.model_fields,
            expected_sideeffect_fields,
        )
    else:
        assert "sideeffect" not in result_model.model_fields

    # Check passthrough fields if expected
    if expected_passthrough_fields:
        assert "passthrough" in result_model.model_fields
        assert result_model.model_fields["passthrough"].annotation
        basic_compare_model_fields(
            result_model.model_fields["passthrough"].annotation.model_fields,
            expected_passthrough_fields,
        )
    else:
        assert "passthrough" not in result_model.model_fields


def test_fuse_metadata_inherited_render():
    """Test render inheritance with filtered fields"""

    class ParentRender(RenderBase):
        render_value_a: str
        render_value_b: int

    class ChildRender(ParentRender):
        render_value_c: float

    class TestController(ControllerBase):
        async def render(self) -> None:
            pass

    metadata = FunctionMetadata(
        action_type=FunctionActionType.SIDEEFFECT,
        function_name="test_function",
        reload_states=tuple([ParentRender.render_value_a]),  # type: ignore
    )

    result_model = fuse_metadata_to_response_typehint(
        metadata,
        TestController(),
        ChildRender,
    )

    # Should only include the specified parent field
    assert "sideeffect" in result_model.model_fields
    assert result_model.model_fields["sideeffect"].annotation

    model_fields = result_model.model_fields["sideeffect"].annotation.model_fields
    basic_compare_model_fields(
        model_fields,
        {
            "render_value_a": FieldInfo.from_annotation(annotation=str),
        },
    )


def test_fuse_metadata_to_response_typehint_unique_models():
    """
    Ensure that render_bases from different files will be considered unique
    in their (module, name) pairing. By default all created modules will inherit
    the mountaineer field module name, so they appear as duplicates to project-wide classes
    with the same individual name.

    """

    # Create render models with same name but different modules
    class RenderA(RenderBase):
        __module__ = "renders.a"
        name: str
        age: int

    class RenderB(RenderBase):
        __module__ = "renders.b"
        name: str
        address: str

    class MockControllerA(ControllerBase):
        __module__ = "controller_a"

        async def render(self) -> RenderA:
            return RenderA(name="example", age=1)

    class MockControllerB(ControllerBase):
        __module__ = "controller_b"

        async def render(self) -> RenderB:
            return RenderB(name="example", address="123 Fake St.")

    # Create two metadata instances with the same function name but different controllers
    metadata_a = FunctionMetadata(
        function_name="get_user", action_type=FunctionActionType.RENDER
    )
    metadata_b = FunctionMetadata(
        function_name="get_user", action_type=FunctionActionType.RENDER
    )

    # Generate response models for each controller/render pair
    response_a = fuse_metadata_to_response_typehint(
        metadata_a, MockControllerA(), RenderA
    )
    response_b = fuse_metadata_to_response_typehint(
        metadata_b, MockControllerB(), RenderB
    )

    # Verify the models have different modules and inherited the ones
    # from the render models
    assert response_a.__module__ == "controller_a"
    assert response_b.__module__ == "controller_b"


def test_annotation_is_metadata():
    assert annotation_is_metadata(Metadata)
    assert annotation_is_metadata(Optional[Metadata])  # type: ignore
    assert annotation_is_metadata(Metadata | None)  # type: ignore
    assert not annotation_is_metadata(str)


class ExampleModel(BaseModel):
    value: str


def test_extract_response_model_from_signature():
    def none_typehint() -> None:
        pass

    def example_typehint(self) -> ExampleModel:
        return ExampleModel(value="example")

    async def example_async_typehint(self) -> ExampleModel:
        return ExampleModel(value="example")

    def example_iterator_typehint(self) -> Iterator[ExampleModel]:
        yield ExampleModel(value="example")

    async def example_async_iterator_typehint(self) -> AsyncIterator[ExampleModel]:
        yield ExampleModel(value="example")

    def no_typehint(self):
        pass

    def explicit_starlette_response(self) -> JSONResponse:
        return JSONResponse(content=dict(value="example"))

    # Regular payload return functions
    assert extract_response_model_from_signature(
        none_typehint,
    ) == (None, ResponseModelType.SINGLE_RESPONSE)
    assert extract_response_model_from_signature(
        example_typehint,
    ) == (ExampleModel, ResponseModelType.SINGLE_RESPONSE)
    assert extract_response_model_from_signature(
        example_async_typehint,
    ) == (ExampleModel, ResponseModelType.SINGLE_RESPONSE)

    # Iterator return functions
    assert extract_response_model_from_signature(
        example_iterator_typehint,
    ) == (ExampleModel, ResponseModelType.ITERATOR_RESPONSE)

    assert extract_response_model_from_signature(
        example_async_iterator_typehint,
    ) == (ExampleModel, ResponseModelType.ITERATOR_RESPONSE)

    assert extract_response_model_from_signature(
        explicit_starlette_response,
    ) == (None, ResponseModelType.SINGLE_RESPONSE)

    # Deprecated but test until we move support for explicit_response
    with pytest.warns(DeprecationWarning):
        assert (
            extract_response_model_from_signature(no_typehint, ExampleModel)
            == (
                ExampleModel,
                ResponseModelType.SINGLE_RESPONSE,
            )
            == (ExampleModel, ResponseModelType.SINGLE_RESPONSE)
        )

    with pytest.warns(DeprecationWarning):
        assert extract_response_model_from_signature(
            no_typehint,
        ) == (None, ResponseModelType.SINGLE_RESPONSE)
