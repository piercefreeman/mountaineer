from dataclasses import dataclass
from typing import Any

from mountaineer.client_builder.interface_builders.action import ActionInterface
from mountaineer.client_builder.interface_builders.base import InterfaceBase
from mountaineer.client_builder.parser import (
    ControllerWrapper,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)


@dataclass
class ControllerInterface(InterfaceBase):
    """
    The Controller interfaces consolidate all actions that belong to
    this controller in the backend. Render function inputs are stored
    separately in their respective ModelInterface.

    """

    name: str
    body: str
    include_superclasses: list[str]
    include_export: bool = True

    @classmethod
    def from_controller(cls, controller: ControllerWrapper):
        fields: dict[str, Any] = {}

        # Convert each action that's directly owned by the controller
        for url, action in controller.actions.items():
            # We don't need a URL here because we just want the type definition, not
            # the full definition
            action_def = ActionInterface.from_action(action, url="", controller=None)

            # If we only have optional params, we will default the inputs to an empty object
            # which makes the whole params object optional
            optional_params = "?" if action_def.default_initializer else ""

            if not action_def.response_type:
                raise ValueError(
                    f"Action {action_def.name} is missing an auto-detected response type"
                )

            action_signature = f"(params{optional_params}: {action_def.typehints}) => {action_def.response_type}"

            fields[TSLiteral(action_def.name)] = TSLiteral(action_signature)

        return cls(
            name=controller.name.global_name,
            body=python_payload_to_typescript(fields),
            include_superclasses=[s.name.global_name for s in controller.superclasses],
        )

    def to_js(self):
        schema_def = f"interface {self.name}"

        if self.include_superclasses:
            schema_def += f" extends {', '.join(self.include_superclasses)}"

        # Our stored body will include the starting/closing brackets
        schema_def += f" {self.body}"

        if self.include_export:
            schema_def = f"export {schema_def}"

        return schema_def
