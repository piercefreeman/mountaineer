from typing import Optional, Type

import pytest
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from mountaineer.actions.fields import (
    FunctionActionType,
    FunctionMetadata,
    annotation_is_metadata,
    fuse_metadata_to_response_typehint,
)
from mountaineer.render import Metadata, RenderBase


class ExampleRenderModel(RenderBase):
    render_value_a: str
    render_value_b: int


class ExamplePassthroughModel(BaseModel):
    passthrough_value_a: str


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
    fused_model = fuse_metadata_to_response_typehint(metadata, render_model)

    if expected_sideeffect_fields:
        assert "sideeffect" in fused_model.model_fields.keys()
        assert fused_model.model_fields["sideeffect"].annotation
        basic_compare_model_fields(
            fused_model.model_fields["sideeffect"].annotation.model_fields,
            expected_sideeffect_fields,
        )

    if expected_passthrough_fields:
        assert "passthrough" in fused_model.model_fields.keys()
        assert fused_model.model_fields["passthrough"].annotation
        basic_compare_model_fields(
            fused_model.model_fields["passthrough"].annotation.model_fields,
            expected_passthrough_fields,
        )

    assert fused_model.__name__ == expected_model_name


def test_annotation_is_metadata():
    assert annotation_is_metadata(Metadata)
    assert annotation_is_metadata(Optional[Metadata])  # type: ignore
    assert annotation_is_metadata(Metadata | None)  # type: ignore
    assert not annotation_is_metadata(str)
