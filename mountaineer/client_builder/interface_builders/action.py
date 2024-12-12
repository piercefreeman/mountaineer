from dataclasses import dataclass
from typing import Any

from mountaineer.client_builder.file_generators.base import CodeBlock
from mountaineer.client_builder.interface_builders.base import InterfaceBase
from mountaineer.client_builder.parser import (
    ActionWrapper,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)


@dataclass
class ActionInterface(InterfaceBase):
    name: str
    parameters: str
    typehints: str
    default_initializer: bool
    response_type: str
    body: list[str]
    required_models: list[str]

    def to_js(self) -> str:
        script = f"export const {self.name} = ({self.parameters} : {self.typehints}"
        if self.default_initializer:
            script += " = {}"
        body_str = "\n".join(self.body)
        script += f"): {self.response_type} => {{ {body_str} }}"
        return script

    @classmethod
    def from_action(cls, action: ActionWrapper, url: str):
        parameters_dict: dict[str, Any] = {}
        typehint_dict: dict[str, Any] = {}
        required_models: list[str] = []

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

        # Add request body if present
        if action.request_body:
            model_name = action.request_body.name
            parameters_dict["requestBody"] = TSLiteral("requestBody")
            typehint_dict[TSLiteral("requestBody")] = TSLiteral(model_name)
            required_models.append(model_name)

        # Merge system parameters
        has_nonsystem_parameters = bool(parameters_dict)
        parameters_dict.update(system_parameters)
        typehint_dict.update(system_typehints)

        request_payload = cls._build_request_payload(url, action, parameters_dict)

        response_type = cls._get_response_type(action)
        if action.response_body:
            required_models.append(action.response_body.name)

        return cls(
            name=action.name,
            parameters=python_payload_to_typescript(parameters_dict),
            typehints=python_payload_to_typescript(typehint_dict),
            default_initializer=not has_nonsystem_parameters,
            response_type=response_type,
            body=["return __request(", CodeBlock.indent(f"  {request_payload}"), ");"],
            required_models=required_models,
        )

    @classmethod
    def _build_request_payload(
        cls, url: str, action: ActionWrapper, parameters: dict[str, Any]
    ) -> str:
        payload: dict[str, Any] = {
            "method": "POST",
            "url": url,
            "path": {},
            "query": {},
            "errors": {},
            "signal": TSLiteral("signal"),
        }

        for param in action.params:
            if param.name in parameters:
                payload["query"][param.name] = TSLiteral(param.name)

        if action.request_body:
            payload["body"] = TSLiteral("requestBody")
            payload["mediaType"] = action.request_body.body_type

        for exception in action.exceptions:
            payload["errors"][exception.status_code] = TSLiteral(exception.name)

        # Clean up empty dicts. These are optional in the request API interface and
        # clean up the generated code
        for key in ["path", "query", "errors"]:
            if not payload[key]:
                del payload[key]

        return python_payload_to_typescript(payload)

    @classmethod
    def _get_response_type(cls, action: ActionWrapper) -> str:
        if not action.response_body:
            return "Promise<void>"

        response_type = action.response_body.name

        if getattr(action.response_body.model, "is_stream", False):
            return f"Promise<AsyncGenerator<{response_type}, void, unknown>>"

        return f"Promise<{response_type}>"
