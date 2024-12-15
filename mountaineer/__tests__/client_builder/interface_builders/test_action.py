from datetime import datetime

import pytest
from pydantic import BaseModel

from mountaineer.__tests__.client_builder.interface_builders.common import (
    create_exception_wrapper,
    create_field_wrapper,
    create_model_wrapper,
)
from mountaineer.actions.fields import FunctionActionType
from mountaineer.client_builder.interface_builders.action import ActionInterface
from mountaineer.client_builder.parser import (
    ActionWrapper,
    ExceptionWrapper,
    FieldWrapper,
    ModelWrapper,
)
from mountaineer.client_builder.types import ListOf, Or
from mountaineer.controller import ControllerBase
from mountaineer.exceptions import APIException


# Test Models
class StandardResponse(BaseModel):
    value: str
    timestamp: datetime


class ErrorResponse(APIException):
    error_code: str
    message: str


class FormData(BaseModel):
    name: str
    email: str


class AlternateResponse(BaseModel):
    status: str
    code: int


@pytest.fixture
def standard_response_wrapper():
    return create_model_wrapper(StandardResponse, "StandardResponse")


@pytest.fixture
def error_response_wrapper():
    return create_exception_wrapper(ErrorResponse, "ErrorResponse", 400)


@pytest.fixture
def form_data_wrapper():
    return create_model_wrapper(FormData, "FormData")


class TestBasicInterfaceGeneration:
    def test_simple_action_interface(self, standard_response_wrapper: ModelWrapper):
        action = ActionWrapper(
            name="simple_action",
            module_name="test_module",
            action_type=FunctionActionType.PASSTHROUGH,
            params=[],
            headers=[],
            request_body=None,
            response_bodies={ControllerBase: standard_response_wrapper},
            exceptions=[],
            is_raw_response=False,
            is_streaming_response=False,
            controller_to_url={ControllerBase: "/api/base/simple_action"},
        )

        interface = ActionInterface.from_action(
            action, "/api/base/simple_action", ControllerBase
        )

        assert interface.name == "simple_action"
        assert "signal?: AbortSignal" in interface.typehints
        assert "Promise<StandardResponse>" in interface.response_type
        assert "StandardResponse" in interface.response_type

    @pytest.mark.parametrize(
        "params, expected_strs, expected_default_initializer",
        [
            # At least one required parameter, should require user input on functions
            (
                [
                    create_field_wrapper("required_param", str, True),
                    create_field_wrapper("optional_param", int, False),
                ],
                ["required_param: string", "optional_param?: number"],
                False,
            ),
            # All optional parameters, should not require user input on functions
            (
                [
                    create_field_wrapper("optional_param", int, False),
                ],
                ["optional_param?: number"],
                True,
            ),
        ],
    )
    def test_action_url_query_parameters(
        self,
        params: list[FieldWrapper],
        expected_strs: list[str],
        expected_default_initializer: bool,
    ):
        action = ActionWrapper(
            name="parametrized_action",
            module_name="test_module",
            action_type=FunctionActionType.PASSTHROUGH,
            params=params,
            headers=[],
            request_body=None,
            response_bodies={
                ControllerBase: create_model_wrapper(
                    StandardResponse, "StandardResponse"
                )
            },
            exceptions=[],
            is_raw_response=False,
            is_streaming_response=False,
            controller_to_url={ControllerBase: "/api/main/parametrized_action"},
        )

        interface = ActionInterface.from_action(
            action, "/api/main/parametrized_action", ControllerBase
        )

        ts_code = interface.to_js()
        for expected_str in expected_strs:
            assert expected_str in ts_code
        assert interface.default_initializer == expected_default_initializer


class TestRequestBodyHandling:
    def test_form_action_interface(self, form_data_wrapper):
        action = ActionWrapper(
            name="form_action",
            module_name="test_module",
            action_type=FunctionActionType.SIDEEFFECT,
            params=[],
            headers=[],
            request_body=form_data_wrapper,
            response_bodies={
                ControllerBase: create_model_wrapper(
                    StandardResponse, "StandardResponse"
                )
            },
            exceptions=[],
            is_raw_response=False,
            is_streaming_response=False,
            controller_to_url={ControllerBase: "/api/main/form"},
        )

        interface = ActionInterface.from_action(
            action, "/api/main/form", ControllerBase
        )

        ts_code = interface.to_js()
        assert "requestBody: FormData" in ts_code
        assert "mediaType" in "".join(interface.body)


class TestResponseTypeHandling:
    def test_raw_response_handling(self, standard_response_wrapper: ModelWrapper):
        action = ActionWrapper(
            name="raw_action",
            module_name="test_module",
            action_type=FunctionActionType.PASSTHROUGH,
            params=[],
            headers=[],
            request_body=None,
            response_bodies={ControllerBase: standard_response_wrapper},
            exceptions=[],
            is_raw_response=True,
            is_streaming_response=False,
            controller_to_url={ControllerBase: "/api/main/raw"},
        )

        interface = ActionInterface.from_action(action, "/api/main/raw", ControllerBase)

        assert "Promise<Response>" in interface.response_type

    def test_streaming_response_handling(self, standard_response_wrapper: ModelWrapper):
        action = ActionWrapper(
            name="stream_action",
            module_name="test_module",
            action_type=FunctionActionType.PASSTHROUGH,
            params=[],
            headers=[],
            request_body=None,
            response_bodies={ControllerBase: standard_response_wrapper},
            exceptions=[],
            is_raw_response=False,
            is_streaming_response=True,
            controller_to_url={ControllerBase: "/api/main/stream"},
        )

        interface = ActionInterface.from_action(
            action, "/api/main/stream", ControllerBase
        )

        assert "AsyncGenerator<StandardResponse" in interface.response_type

    def test_multiple_response_types(self):
        class ResponseA(BaseModel):
            value: str

        class ResponseB(BaseModel):
            code: int

        class ControllerA(ControllerBase):
            pass

        class ControllerB(ControllerBase):
            pass

        action = ActionWrapper(
            name="multi_action",
            module_name="test_module",
            action_type=FunctionActionType.PASSTHROUGH,
            params=[],
            headers=[],
            request_body=None,
            response_bodies={
                ControllerA: create_model_wrapper(ResponseA, "ResponseA"),
                ControllerB: create_model_wrapper(ResponseB, "ResponseB"),
            },
            exceptions=[],
            is_raw_response=False,
            is_streaming_response=False,
            controller_to_url={ControllerA: "/api/a", ControllerB: "/api/b"},
        )

        interface = ActionInterface.from_action(action, "/api/multi", None)

        assert "ResponseA" in interface.response_type
        assert "ResponseB" in interface.response_type
        assert "|" in interface.response_type


class TestErrorHandling:
    def test_error_models(self, error_response_wrapper: ExceptionWrapper):
        action = ActionWrapper(
            name="error_action",
            module_name="test_module",
            action_type=FunctionActionType.PASSTHROUGH,
            params=[],
            headers=[],
            request_body=None,
            response_bodies={
                ControllerBase: create_model_wrapper(
                    StandardResponse, "StandardResponse"
                )
            },
            exceptions=[error_response_wrapper],
            is_raw_response=False,
            is_streaming_response=False,
            controller_to_url={ControllerBase: "/api/main/error"},
        )

        interface = ActionInterface.from_action(
            action, "/api/main/error", ControllerBase
        )

        error_payload = "".join(interface.body)
        assert "ErrorResponse" in error_payload
        assert "errors" in error_payload
        assert "400" in error_payload


class TestTypeScriptGeneration:
    def test_complex_payload_conversion(self):
        action = ActionWrapper(
            name="complex_action",
            module_name="test_module",
            action_type=FunctionActionType.PASSTHROUGH,
            params=[
                create_field_wrapper("list_param", ListOf(str)),
                create_field_wrapper("optional_param", Or(str, None), False),
            ],
            headers=[],
            request_body=None,
            response_bodies={
                ControllerBase: create_model_wrapper(
                    StandardResponse, "StandardResponse"
                )
            },
            exceptions=[],
            is_raw_response=False,
            is_streaming_response=False,
            controller_to_url={ControllerBase: "/api/complex"},
        )

        interface = ActionInterface.from_action(action, "/api/complex", ControllerBase)

        ts_code = interface.to_js()
        assert "list_param: Array<string>" in ts_code
        assert "optional_param?: string" in ts_code
