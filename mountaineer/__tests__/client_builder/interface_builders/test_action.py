from datetime import datetime
from typing import Any, Dict, List, Optional, Type, Union

import pytest
from pydantic import BaseModel

from mountaineer.actions.passthrough_dec import passthrough
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.client_builder.interface_builders.action import ActionInterface
from mountaineer.client_builder.parser import ActionWrapper, ControllerParser
from mountaineer.controller import ControllerBase


# Response Models
class StandardResponse(BaseModel):
    value: str
    timestamp: datetime


class ErrorResponse(BaseModel):
    error_code: str
    message: str


class FormData(BaseModel):
    name: str
    email: str


class AlternateResponse(BaseModel):
    status: str
    code: int


# Base Controller with shared functionality
class BaseApiController(ControllerBase):
    url: str = "/api/base"

    @passthrough
    def simple_action(self) -> StandardResponse:
        pass


class MainController(BaseApiController):
    url: str = "/api/main"

    @passthrough
    def parameterized_action(
        self, required_param: str, optional_param: int = 0
    ) -> StandardResponse:
        pass

    @sideeffect
    def form_action(self, data: FormData) -> StandardResponse:
        pass

    @passthrough
    def error_action(self) -> StandardResponse:
        pass

    class Config:
        error_models: Dict[Type[Exception], Type[BaseModel]] = {
            ValueError: ErrorResponse
        }

    @passthrough
    def raw_action(self) -> StandardResponse:
        pass

    class Config:
        raw_response: bool = True

    @passthrough
    def stream_action(self) -> StandardResponse:
        pass

    class Config:
        stream_response: bool = True


class SpecializedController(MainController):
    url: str = "/api/special"

    @passthrough
    def override_action(self) -> AlternateResponse:
        pass


# Test Fixtures
@pytest.fixture
def parser() -> ControllerParser:
    return ControllerParser()


@pytest.fixture
def base_controller_wrapper(parser: ControllerParser) -> ControllerWrapper:
    return parser.parse_controller(BaseApiController)


@pytest.fixture
def main_controller_wrapper(parser: ControllerParser) -> ControllerWrapper:
    return parser.parse_controller(MainController)


@pytest.fixture
def specialized_controller_wrapper(parser: ControllerParser) -> ControllerWrapper:
    return parser.parse_controller(SpecializedController)


@pytest.fixture
def simple_action(base_controller_wrapper: ControllerWrapper) -> ActionWrapper:
    return base_controller_wrapper.actions["simple_action"]


@pytest.fixture
def parameterized_action(main_controller_wrapper: ControllerWrapper) -> ActionWrapper:
    return main_controller_wrapper.actions["parameterized_action"]


@pytest.fixture
def form_action(main_controller_wrapper: ControllerWrapper) -> ActionWrapper:
    return main_controller_wrapper.actions["form_action"]


# Test Classes
class TestBasicInterfaceGeneration:
    def test_simple_action_interface(self, simple_action: ActionWrapper) -> None:
        interface: ActionInterface = ActionInterface.from_action(
            simple_action, "/api/base/simple_action", BaseApiController
        )

        assert interface.name == "simple_action"
        assert "signal?: AbortSignal" in interface.typehints
        assert "Promise<StandardResponse>" in interface.response_type
        assert "StandardResponse" in interface.required_models

    def test_parameterized_action_interface(
        self, parameterized_action: ActionWrapper
    ) -> None:
        interface: ActionInterface = ActionInterface.from_action(
            parameterized_action, "/api/main/parameterized_action", MainController
        )

        ts_code: str = interface.to_js()
        assert "required_param: string" in ts_code
        assert "optional_param?: number" in ts_code
        assert not interface.default_initializer

    @pytest.mark.parametrize(
        "param_name,param_type",
        [
            ("string_param", "string"),
            ("number_param", "number"),
            ("boolean_param", "boolean"),
        ],
    )
    def test_parameter_type_conversion(
        self, parser: ControllerParser, param_name: str, param_type: str
    ) -> None:
        class ParamController(ControllerBase):
            @passthrough
            def param_action(self, **kwargs: Any) -> StandardResponse:
                pass

        # Dynamically add parameter
        setattr(
            ParamController.param_action,
            "__annotations__",
            {param_name: eval(param_type.capitalize())},
        )

        wrapper: ControllerWrapper = parser.parse_controller(ParamController)
        action: ActionWrapper = wrapper.actions["param_action"]
        interface: ActionInterface = ActionInterface.from_action(
            action, f"/api/param/{param_name}", ParamController
        )

        assert f"{param_name}: {param_type}" in interface.typehints


class TestRequestBodyHandling:
    def test_form_action_interface(self, form_action: ActionWrapper) -> None:
        interface: ActionInterface = ActionInterface.from_action(
            form_action, "/api/main/form", MainController
        )

        ts_code: str = interface.to_js()
        assert "requestBody: FormData" in ts_code
        assert "FormData" in interface.required_models
        assert "mediaType" in "".join(interface.body)

    def test_empty_body_handling(self, simple_action: ActionWrapper) -> None:
        interface: ActionInterface = ActionInterface.from_action(
            simple_action, "/api/simple", BaseApiController
        )

        ts_code: str = interface.to_js()
        assert "requestBody" not in ts_code
        assert "mediaType" not in "".join(interface.body)


class TestResponseTypeHandling:
    @pytest.mark.parametrize(
        "config_attr,expected_type",
        [
            (None, "Promise<StandardResponse>"),
            ("raw_response", "Promise<Response>"),
            (
                "stream_response",
                "Promise<AsyncGenerator<StandardResponse, void, unknown>>",
            ),
        ],
    )
    def test_response_types(
        self, parser: ControllerParser, config_attr: Optional[str], expected_type: str
    ) -> None:
        class ResponseController(ControllerBase):
            @passthrough
            def response_action(self) -> StandardResponse:
                pass

        if config_attr:
            setattr(ResponseController.Config, config_attr, True)

        wrapper: ControllerWrapper = parser.parse_controller(ResponseController)
        action: ActionWrapper = wrapper.actions["response_action"]
        interface: ActionInterface = ActionInterface.from_action(
            action, "/api/response", ResponseController
        )

        assert expected_type in interface.response_type

    def test_multiple_response_types(self, parser: ControllerParser) -> None:
        class MultiResponseController(ControllerBase):
            @passthrough
            def multi_action(self) -> Union[StandardResponse, AlternateResponse]:
                pass

        wrapper: ControllerWrapper = parser.parse_controller(MultiResponseController)
        action: ActionWrapper = wrapper.actions["multi_action"]
        interface: ActionInterface = ActionInterface.from_action(
            action, "/api/multi", MultiResponseController
        )

        assert "StandardResponse" in interface.response_type
        assert "AlternateResponse" in interface.response_type
        assert "|" in interface.response_type


class TestErrorHandling:
    def test_error_models(self, main_controller_wrapper: ControllerWrapper) -> None:
        action: ActionWrapper = main_controller_wrapper.actions["error_action"]
        interface: ActionInterface = ActionInterface.from_action(
            action, "/api/main/error", MainController
        )

        error_payload: str = "".join(interface.body)
        assert "ErrorResponse" in interface.required_models
        assert "errors" in error_payload
        assert "ValueError" in error_payload


class TestTypeScriptGeneration:
    def test_complex_payload_conversion(self, parser: ControllerParser) -> None:
        class ComplexParamController(ControllerBase):
            @passthrough
            def complex_action(
                self,
                list_param: List[str],
                dict_param: Dict[str, int],
                optional_param: Optional[str] = None,
            ) -> StandardResponse:
                pass

        wrapper: ControllerWrapper = parser.parse_controller(ComplexParamController)
        action: ActionWrapper = wrapper.actions["complex_action"]
        interface: ActionInterface = ActionInterface.from_action(
            action, "/api/complex", ComplexParamController
        )

        ts_code: str = interface.to_js()
        assert "list_param: Array<string>" in ts_code
        assert "dict_param: Record<string, number>" in ts_code
        assert "optional_param?: string" in ts_code

    def test_nested_payload_structure(self, parser: ControllerParser) -> None:
        class NestedData(BaseModel):
            items: List[FormData]
            metadata: Dict[str, str]

        class NestedController(ControllerBase):
            @passthrough
            def nested_action(self, data: NestedData) -> StandardResponse:
                pass

        wrapper: ControllerWrapper = parser.parse_controller(NestedController)
        action: ActionWrapper = wrapper.actions["nested_action"]
        interface: ActionInterface = ActionInterface.from_action(
            action, "/api/nested", NestedController
        )

        assert "NestedData" in interface.required_models
        assert "FormData" in interface.required_models


class TestInheritanceScenarios:
    def test_inherited_action_interfaces(
        self,
        base_controller_wrapper: ControllerWrapper,
        specialized_controller_wrapper: ControllerWrapper,
    ) -> None:
        base_action: ActionWrapper = base_controller_wrapper.actions["simple_action"]
        base_interface: ActionInterface = ActionInterface.from_action(
            base_action, "/api/base/simple", BaseApiController
        )

        # Same action through inherited controller
        inherited_interface: ActionInterface = ActionInterface.from_action(
            base_action, "/api/special/simple", SpecializedController
        )

        assert base_interface.name == inherited_interface.name
        assert base_interface.response_type == inherited_interface.response_type
        assert "/api/base" in "".join(base_interface.body)
        assert "/api/special" in "".join(inherited_interface.body)

    def test_override_action_interface(
        self, specialized_controller_wrapper: ControllerWrapper
    ) -> None:
        action: ActionWrapper = specialized_controller_wrapper.actions[
            "override_action"
        ]
        interface: ActionInterface = ActionInterface.from_action(
            action, "/api/special/override", SpecializedController
        )

        assert "AlternateResponse" in interface.response_type
        assert "StandardResponse" not in interface.response_type
        assert "AlternateResponse" in interface.required_models
