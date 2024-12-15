from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from mountaineer.__tests__.client_builder.interface_builders.common import (
    create_action_wrapper,
    create_controller_wrapper,
    create_model_wrapper,
)
from mountaineer.actions.fields import FunctionActionType
from mountaineer.client_builder.interface_builders.controller import ControllerInterface
from mountaineer.client_builder.parser import (
    FieldWrapper,
)
from mountaineer.client_builder.types import Or


# Test Models
class SimpleResponse(BaseModel):
    message: str
    timestamp: datetime


class ComplexResponse(BaseModel):
    data: dict[str, Any]
    status: bool
    metadata: Optional[dict[str, str]] = None


class FormData(BaseModel):
    name: str
    email: str
    preferences: dict[str, bool] = {}


class TestBasicInterfaceGeneration:
    def test_simple_controller_interface(self):
        health_check = create_action_wrapper(
            "health_check", response_model=SimpleResponse
        )

        controller = create_controller_wrapper(
            "ApiBaseController", actions={"health_check": health_check}
        )

        interface = ControllerInterface.from_controller(controller)
        ts_code = interface.to_js()

        assert "export interface" in ts_code
        assert "ApiBaseController" in ts_code
        assert "health_check" in ts_code
        assert "SimpleResponse" in ts_code

    def test_controller_with_multiple_actions(self):
        get_resource = create_action_wrapper(
            "get_resource",
            params=[FieldWrapper("id", str, True)],
            response_model=SimpleResponse,
        )

        update_resource = create_action_wrapper(
            "update_resource",
            request_body=create_model_wrapper(FormData, "FormData"),
            response_model=ComplexResponse,
            action_type=FunctionActionType.SIDEEFFECT,
        )

        controller = create_controller_wrapper(
            "ResourceController",
            actions={"get_resource": get_resource, "update_resource": update_resource},
        )

        interface = ControllerInterface.from_controller(controller)
        ts_code = interface.to_js()

        assert "get_resource" in ts_code
        assert "update_resource" in ts_code
        assert "params: {" in ts_code
        assert "FormData" in ts_code


class TestInheritanceHandling:
    def test_single_inheritance(self):
        # Create base controller
        base_controller = create_controller_wrapper(
            "ApiBaseController",
            actions={
                "health_check": create_action_wrapper(
                    "health_check", response_model=SimpleResponse
                )
            },
        )

        # Create resource controller inheriting from base
        resource_controller = create_controller_wrapper(
            "ResourceController",
            actions={
                "get_resource": create_action_wrapper(
                    "get_resource", response_model=SimpleResponse
                )
            },
            superclasses=[base_controller],
        )

        interface = ControllerInterface.from_controller(resource_controller)

        assert "ApiBaseController" in interface.include_superclasses
        assert "extends ApiBaseController" in interface.to_js()

    def test_multi_level_inheritance(self):
        # Create the inheritance chain
        base_controller = create_controller_wrapper("ApiBaseController")
        resource_controller = create_controller_wrapper(
            "ResourceController", superclasses=[base_controller]
        )
        extended_controller = create_controller_wrapper(
            "ExtendedController",
            actions={
                "specialized_action": create_action_wrapper(
                    "specialized_action", response_model=ComplexResponse
                )
            },
            superclasses=[resource_controller],
        )

        interface = ControllerInterface.from_controller(extended_controller)

        # Only the immediate superclasses should be specified
        assert "ResourceController" in interface.include_superclasses
        assert "extends ResourceController" in interface.to_js()
        assert "ApiBaseController" not in interface.to_js()


class TestParameterHandling:
    def test_optional_parameters(self):
        action = create_action_wrapper(
            "optional_action",
            params=[
                FieldWrapper("param1", Or(str, None), False),
                FieldWrapper("param2", int, False),
            ],
            response_model=SimpleResponse,
        )

        controller = create_controller_wrapper(
            "OptionalParamsController", actions={"optional_action": action}
        )

        interface = ControllerInterface.from_controller(controller)
        ts_code = interface.to_js()

        assert "params?: {" in ts_code
        assert "param1?: string" in ts_code
        assert "param2?: number" in ts_code

    def test_required_parameters(self):
        action = create_action_wrapper(
            "required_action",
            params=[FieldWrapper("required_param", str, True)],
            response_model=SimpleResponse,
        )

        controller = create_controller_wrapper(
            "RequiredParamsController", actions={"required_action": action}
        )

        interface = ControllerInterface.from_controller(controller)
        ts_code = interface.to_js()

        assert "params: {" in ts_code
        assert "required_param: string" in ts_code
