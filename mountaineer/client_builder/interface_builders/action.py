from dataclasses import dataclass
from typing import Any, Type

from mountaineer.client_builder.file_generators.base import CodeBlock
from mountaineer.client_builder.interface_builders.base import InterfaceBase
from mountaineer.client_builder.parser import (
    ActionWrapper,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)
from mountaineer.controller import ControllerBase


@dataclass
class ActionInterface(InterfaceBase):
    name: str
    parameters: str
    typehints: str
    default_initializer: bool
    response_type: str
    body: list[str]

    def to_js(self) -> str:
        script = f"export const {self.name} = ({self.parameters} : {self.typehints}"
        if self.default_initializer:
            script += " = {}"
        body_str = "\n".join(self.body)
        script += f"): {self.response_type} => {{ {body_str} }}"
        return script

    @classmethod
    def from_action(
        cls, action: ActionWrapper, url: str, controller: Type[ControllerBase] | None
    ):
        """
        If controller is None, we should take the union of all response bodies. This is used for global definitions
        where the exact model might be different by the concrete controller (like for @sideeffects that must include
        the specific controller's render model).

        """
        parameters_dict: dict[str, Any] = {}
        typehint_dict: dict[str, Any] = {}

        # System parameters (always optional)
        system_parameters = {"signal": TSLiteral("signal")}
        system_typehints: dict[str, Any] = {
            TSLiteral("signal?"): TSLiteral("AbortSignal")
        }

        # Add path/query parameters
        for param in action.params:
            parameters_dict[param.name] = TSLiteral(param.name)
            typehint_dict[
                TSLiteral(f"{param.name}{'?' if not param.required else ''}")
            ] = TSLiteral(cls._get_annotated_value(param.value))

        for header in action.headers:
            parameters_dict[header.name] = TSLiteral(header.name)
            typehint_dict[
                TSLiteral(f"{header.name}{'?' if not header.required else ''}")
            ] = TSLiteral(cls._get_annotated_value(header.value))

        # Add request body if present
        if action.request_body:
            model_name = action.request_body.name.global_name
            parameters_dict["requestBody"] = TSLiteral("requestBody")
            typehint_dict[TSLiteral("requestBody")] = TSLiteral(model_name)

        # Merge system parameters
        parameters_dict.update(system_parameters)
        typehint_dict.update(system_typehints)

        request_payload = cls._build_request_payload(url, action, parameters_dict)

        response_types: set[str] = set()
        controllers = [controller] if controller else action.response_bodies.keys()
        if controllers:
            for controller in controllers:
                response_types.add(cls._get_response_type(action, controller))
        else:
            # Fallback in the case that no concrete controllers are mounted with this action
            # In this case we just use a generic typehint for the return value
            response_types.add(cls._get_response_type(action, None))

        return cls(
            name=action.name,
            parameters=python_payload_to_typescript(parameters_dict),
            typehints=python_payload_to_typescript(typehint_dict),
            default_initializer=not action.has_required_params(),
            response_type=" | ".join(response_types),
            body=["return __request(", CodeBlock.indent(f"  {request_payload}"), ");"],
        )

    @classmethod
    def _build_request_payload(
        cls, url: str, action: ActionWrapper, parameters: dict[str, Any]
    ) -> str:
        payload: dict[str, Any] = {
            "method": "POST",
            "url": url,
            "path": {},
            "headers": {},
            "query": {},
            "errors": {},
            "signal": TSLiteral("signal"),
        }

        for param in action.params:
            if param.name in parameters:
                payload["query"][param.name] = TSLiteral(param.name)

        for header in action.headers:
            if header.name in parameters:
                payload["headers"][header.name] = TSLiteral(header.name)

        if action.request_body:
            payload["body"] = TSLiteral("requestBody")
            payload["mediaType"] = action.request_body.body_type

        for exception in action.exceptions:
            payload["errors"][exception.status_code] = TSLiteral(
                exception.name.global_name
            )

        if action.is_raw_response:
            payload["outputFormat"] = "raw"

        # Support for server-events
        if action.is_streaming_response:
            payload["eventStreamResponse"] = True

        # Clean up empty dicts. These are optional in the request API interface and
        # clean up the generated code
        for key in ["path", "headers", "query", "errors"]:
            if not payload[key]:
                del payload[key]

        return python_payload_to_typescript(
            {TSLiteral(key): value for key, value in payload.items()}
        )

    @classmethod
    def _get_response_type(
        cls, action: ActionWrapper, controller: Type[ControllerBase] | None
    ) -> str:
        if action.is_raw_response:
            return "Promise<Response>"

        if not controller:
            return "Promise<any>"

        response_body = cls._get_response_body(action, controller)
        if not response_body:
            return "Promise<void>"

        response_type = response_body.name.global_name

        if action.is_streaming_response:
            return f"Promise<AsyncGenerator<{response_type}, void, unknown>>"

        return f"Promise<{response_type}>"

    @classmethod
    def _get_response_body(
        cls, action: ActionWrapper, controller: Type[ControllerBase]
    ):
        return action.response_bodies.get(controller)
