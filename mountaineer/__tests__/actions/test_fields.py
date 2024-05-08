from typing import AsyncIterator, Iterator, Optional, Type

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
    get_function_metadata,
)
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.controller import ControllerBase
from mountaineer.render import Metadata, RenderBase


class ExampleRenderModel(RenderBase):
    render_value_a: str
    render_value_b: int


class ExamplePassthroughModel(BaseModel):
    passthrough_value_a: str


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
        # Standard sideeffect with every value included in the refresh
        (
            FunctionMetadata(
                action_type=FunctionActionType.SIDEEFFECT,
                function_name="example_function",
            ),
            ExampleRenderModel,
            "ExampleFunctionResponse",
            {
                # The metadata field should not be included in the sideeffect
                # response, only the defined keys
                "render_value_a": FieldInfo.from_annotation(
                    annotation=str,
                ),
                "render_value_b": FieldInfo.from_annotation(
                    annotation=int,
                ),
            },
            {},
        ),
        # Sideeffect with masked value payload, only should include the masked value
        (
            FunctionMetadata(
                action_type=FunctionActionType.SIDEEFFECT,
                function_name="example_function",
                reload_states=tuple(
                    [
                        # At runtime this will evaluate to the render_value_a metadata definition
                        ExampleRenderModel.render_value_a,  # type: ignore
                    ]
                ),
            ),
            ExampleRenderModel,
            "ExampleFunctionResponse",
            {
                "render_value_a": FieldInfo.from_annotation(
                    annotation=str,
                ),
            },
            {},
        ),
        # Passthrough function markup, should include the passthrough value
        # and no sideeffect value
        (
            FunctionMetadata(
                action_type=FunctionActionType.PASSTHROUGH,
                function_name="example_function",
                passthrough_model=ExamplePassthroughModel,
            ),
            ExampleRenderModel,
            "ExampleFunctionResponse",
            {},
            {
                "passthrough_value_a": FieldInfo.from_annotation(
                    annotation=str,
                ),
            },
        ),
    ],
)
def test_fuse_metadata_to_response_typehint(
    metadata: FunctionMetadata,
    render_model: Type[RenderBase],
    expected_model_name: str,
    expected_sideeffect_fields: dict[str, FieldInfo],
    expected_passthrough_fields: dict[str, FieldInfo],
):
    sample_controller = ExampleController()
    raw_model = fuse_metadata_to_response_typehint(
        metadata, sample_controller, render_model
    )

    if expected_sideeffect_fields:
        assert "sideeffect" in raw_model.model_fields.keys()
        assert raw_model.model_fields["sideeffect"].annotation
        basic_compare_model_fields(
            raw_model.model_fields["sideeffect"].annotation.model_fields,
            expected_sideeffect_fields,
        )

    if expected_passthrough_fields:
        assert "passthrough" in raw_model.model_fields.keys()
        assert raw_model.model_fields["passthrough"].annotation
        basic_compare_model_fields(
            raw_model.model_fields["passthrough"].annotation.model_fields,
            expected_passthrough_fields,
        )

    assert raw_model.__name__ == expected_model_name


class ParentRender(RenderBase):
    render_value_a: str


class ChildRender(ParentRender):
    render_value_b: int


def test_fuse_metadata_to_response_typehint_inherit_render():
    class ParentController(ControllerBase):
        def render(self) -> ParentRender:
            return ParentRender(render_value_a="example")

        @sideeffect(reload=(ParentRender.render_value_a,))
        def sideeffect(self) -> None:
            pass

    class ChildController(ParentController):
        def render(self) -> ChildRender:
            return ChildRender(render_value_a="example", render_value_b=1)

    model_fused = fuse_metadata_to_response_typehint(
        get_function_metadata(ChildController.sideeffect),
        ChildController(),
        ChildRender,
    )
    assert set(
        model_fused.model_json_schema()["$defs"]["SideeffectResponseSideEffect"][
            "properties"
        ].keys()
    ) == {"render_value_a"}


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
