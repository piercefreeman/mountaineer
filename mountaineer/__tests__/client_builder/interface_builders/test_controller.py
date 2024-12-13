from datetime import datetime
from typing import Any, Dict, List, Optional, Type

import pytest
from pydantic import BaseModel

from mountaineer.actions.passthrough_dec import passthrough
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.client_builder.interface_builders.controller import ControllerInterface
from mountaineer.client_builder.parser import ControllerParser, ControllerWrapper
from mountaineer.controller import ControllerBase


# Response Models
class SimpleResponse(BaseModel):
    message: str
    timestamp: datetime


class ComplexResponse(BaseModel):
    data: Dict[str, Any]
    status: bool
    metadata: Optional[Dict[str, str]] = None


class FormData(BaseModel):
    name: str
    email: str
    preferences: Dict[str, bool] = {}


# Base Controllers
class ApiBaseController(ControllerBase):
    """Base API controller with common functionality"""

    @passthrough
    def health_check(self) -> SimpleResponse:
        pass


class ResourceController(ApiBaseController):
    """Basic resource controller"""

    @passthrough
    def get_resource(self, id: str) -> SimpleResponse:
        pass

    @sideeffect
    def update_resource(self, form: FormData) -> ComplexResponse:
        pass


class ExtendedController(ResourceController):
    """Controller with additional specialized actions"""

    @passthrough
    def specialized_action(self) -> ComplexResponse:
        pass

    @passthrough
    def override_resource(self, id: str) -> ComplexResponse:
        pass


# Test Fixtures
@pytest.fixture
def parser() -> ControllerParser:
    return ControllerParser()


@pytest.fixture
def base_controller_wrapper(parser: ControllerParser) -> ControllerWrapper:
    return parser.parse_controller(ApiBaseController)


@pytest.fixture
def resource_controller_wrapper(parser: ControllerParser) -> ControllerWrapper:
    return parser.parse_controller(ResourceController)


@pytest.fixture
def extended_controller_wrapper(parser: ControllerParser) -> ControllerWrapper:
    return parser.parse_controller(ExtendedController)


class TestBasicInterfaceGeneration:
    def test_simple_controller_interface(
        self, base_controller_wrapper: ControllerWrapper
    ) -> None:
        interface: ControllerInterface = ControllerInterface.from_controller(
            base_controller_wrapper
        )

        ts_code: str = interface.to_js()
        assert "export interface" in ts_code
        assert "ApiBaseController" in ts_code
        assert "health_check" in ts_code
        assert "SimpleResponse" in ts_code

    def test_controller_with_multiple_actions(
        self, resource_controller_wrapper: ControllerWrapper
    ) -> None:
        interface: ControllerInterface = ControllerInterface.from_controller(
            resource_controller_wrapper
        )

        ts_code: str = interface.to_js()
        assert "get_resource" in ts_code
        assert "update_resource" in ts_code
        assert "params: {" in ts_code
        assert "FormData" in ts_code

    def test_non_exported_interface(
        self, resource_controller_wrapper: ControllerWrapper
    ) -> None:
        interface: ControllerInterface = ControllerInterface.from_controller(
            resource_controller_wrapper
        )
        interface.include_export = False

        ts_code: str = interface.to_js()
        assert "export" not in ts_code
        assert "interface ResourceController" in ts_code


class TestInheritanceHandling:
    def test_single_inheritance(
        self, resource_controller_wrapper: ControllerWrapper
    ) -> None:
        interface: ControllerInterface = ControllerInterface.from_controller(
            resource_controller_wrapper
        )

        assert "ApiBaseController" in interface.include_superclasses
        ts_code: str = interface.to_js()
        assert "extends ApiBaseController" in ts_code

    def test_multi_level_inheritance(
        self, extended_controller_wrapper: ControllerWrapper
    ) -> None:
        interface: ControllerInterface = ControllerInterface.from_controller(
            extended_controller_wrapper
        )

        assert "ResourceController" in interface.include_superclasses
        ts_code: str = interface.to_js()
        assert "extends ResourceController" in ts_code

    def test_action_inheritance(
        self, extended_controller_wrapper: ControllerWrapper
    ) -> None:
        interface: ControllerInterface = ControllerInterface.from_controller(
            extended_controller_wrapper
        )
        ts_code: str = interface.to_js()

        # Should include own actions and inherited ones
        assert "specialized_action" in ts_code
        assert "override_resource" in ts_code
        assert "health_check" not in ts_code  # Base actions not included directly


class TestParameterHandling:
    def test_optional_parameters(self, parser: ControllerParser) -> None:
        class OptionalParamsController(ControllerBase):
            @passthrough
            def optional_action(
                self, param1: Optional[str] = None, param2: int = 0
            ) -> SimpleResponse:
                pass

        wrapper: ControllerWrapper = parser.parse_controller(OptionalParamsController)
        interface: ControllerInterface = ControllerInterface.from_controller(wrapper)

        ts_code: str = interface.to_js()
        assert "params?: {" in ts_code
        assert "param1?: string" in ts_code
        assert "param2?: number" in ts_code

    def test_required_parameters(self, parser: ControllerParser) -> None:
        class RequiredParamsController(ControllerBase):
            @passthrough
            def required_action(self, required_param: str) -> SimpleResponse:
                pass

        wrapper: ControllerWrapper = parser.parse_controller(RequiredParamsController)
        interface: ControllerInterface = ControllerInterface.from_controller(wrapper)

        ts_code: str = interface.to_js()
        assert "params: {" in ts_code  # No optional modifier
        assert "required_param: string" in ts_code


class TestEdgeCases:
    def test_empty_controller(self, parser: ControllerParser) -> None:
        class EmptyController(ControllerBase):
            pass

        wrapper: ControllerWrapper = parser.parse_controller(EmptyController)
        interface: ControllerInterface = ControllerInterface.from_controller(wrapper)

        ts_code: str = interface.to_js()
        assert "interface EmptyController {}" in ts_code

    def test_missing_response_type(self, parser: ControllerParser) -> None:
        class InvalidController(ControllerBase):
            @passthrough
            def invalid_action(self) -> None:
                pass

        wrapper: ControllerWrapper = parser.parse_controller(InvalidController)
        with pytest.raises(ValueError, match="missing an auto-detected response type"):
            ControllerInterface.from_controller(wrapper)

    def test_complex_response_types(self, parser: ControllerParser) -> None:
        class ComplexReturnController(ControllerBase):
            @passthrough
            def nested_action(self) -> Dict[str, List[SimpleResponse]]:
                pass

        wrapper: ControllerWrapper = parser.parse_controller(ComplexReturnController)
        interface: ControllerInterface = ControllerInterface.from_controller(wrapper)

        ts_code: str = interface.to_js()
        assert "Record<string, Array<SimpleResponse>>" in ts_code


class TestTypeScriptGeneration:
    @pytest.mark.parametrize(
        "controller_name,expected",
        [
            ("ValidController", "interface ValidController"),
            ("My_Controller", "interface My_Controller"),
            ("API_V1_Controller", "interface API_V1_Controller"),
        ],
    )
    def test_interface_naming(
        self, parser: ControllerParser, controller_name: str, expected: str
    ) -> None:
        # Dynamically create controller class
        controller: Type[ControllerBase] = type(
            controller_name,
            (ControllerBase,),
            {"simple_action": passthrough(lambda self: SimpleResponse(message="test"))},
        )

        wrapper: ControllerWrapper = parser.parse_controller(controller)
        interface: ControllerInterface = ControllerInterface.from_controller(wrapper)

        assert expected in interface.to_js()

    def test_complex_type_definitions(self, parser: ControllerParser) -> None:
        class ComplexTypesController(ControllerBase):
            @passthrough
            def complex_action(
                self,
                dict_param: Dict[str, Any],
                optional_dict: Optional[Dict[str, SimpleResponse]] = None,
            ) -> ComplexResponse:
                pass

        wrapper: ControllerWrapper = parser.parse_controller(ComplexTypesController)
        interface: ControllerInterface = ControllerInterface.from_controller(wrapper)

        ts_code: str = interface.to_js()
        assert "Record<string, any>" in ts_code
        assert "Record<string, SimpleResponse> | undefined" in ts_code

    def test_multiline_formatting(
        self, resource_controller_wrapper: ControllerWrapper
    ) -> None:
        interface: ControllerInterface = ControllerInterface.from_controller(
            resource_controller_wrapper
        )
        ts_code: str = interface.to_js()

        # Check basic formatting
        assert "{\n" in ts_code
        assert "\n}" in ts_code
        # Each action should be on its own line
        assert ts_code.count("\n") >= len(resource_controller_wrapper.actions)
