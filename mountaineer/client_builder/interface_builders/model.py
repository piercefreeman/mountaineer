from dataclasses import dataclass
from typing import Any

from mountaineer.client_builder.interface_builders.base import InterfaceBase
from mountaineer.client_builder.parser import (
    ModelWrapper,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)


@dataclass
class ModelInterface(InterfaceBase):
    name: str
    body: str
    include_superclasses: list[str]
    include_export: bool = True

    @classmethod
    def from_model(cls, value: ModelWrapper):
        fields: dict[str, Any] = {}
        for field in value.value_models:
            field_name = f"{field.name}{'?' if not field.required else ''}"
            field_type = cls._get_annotated_value(field.value)
            fields[TSLiteral(field_name)] = TSLiteral(field_type)

        return cls(
            name=value.name.global_name,
            body=python_payload_to_typescript(fields),
            include_superclasses=[s.name.global_name for s in value.superclasses],
        )

    def to_js(self) -> str:
        schema_def = f"interface {self.name}"

        if self.include_superclasses:
            schema_def += f" extends {', '.join(self.include_superclasses)}"

        # Our stored body will include the starting/closing brackets
        schema_def += f" {self.body}"

        if self.include_export:
            schema_def = f"export {schema_def}"

        return schema_def
