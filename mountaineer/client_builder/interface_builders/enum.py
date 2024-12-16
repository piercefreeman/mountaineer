from dataclasses import dataclass
from typing import Any

from mountaineer.client_builder.interface_builders.base import InterfaceBase
from mountaineer.client_builder.parser import (
    EnumWrapper,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)


@dataclass
class EnumInterface(InterfaceBase):
    name: str
    body: str
    include_export: bool = True

    @classmethod
    def from_enum(cls, enum: EnumWrapper):
        fields: dict[str, Any] = {}

        # Mirror the format of JS enums
        # https://www.typescriptlang.org/docs/handbook/enums.html
        # enum Direction {
        #  Up = 1,
        #  Down,
        #  Left,
        #  Right,
        # }
        for name, value in enum.enum.__members__.items():
            fields[TSLiteral(name)] = value.value

        return cls(
            name=enum.name.global_name,
            # Optional spacing, but make for better enum definitions (A = 'A')
            body=python_payload_to_typescript(fields, dict_equality=" ="),
        )

    def to_js(self) -> str:
        schema_def = f"enum {self.name}"

        # Body includes the { } tokens
        schema_def += f" {self.body}"

        if self.include_export:
            schema_def = f"export {schema_def}"

        return schema_def
