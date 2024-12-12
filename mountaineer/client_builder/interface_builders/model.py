from dataclasses import dataclass

from mountaineer.client_builder.interface_builders.base import InterfaceBase
from mountaineer.client_builder.parser import (
    EnumWrapper,
)


@dataclass
class EnumInterface(InterfaceBase):

    name: str
    body: str
    include_superclasses: list[str]
    include_export: bool = True

    def from_enum(self, enum: EnumWrapper):
        pass

    def to_js(self) -> str:
        schema_def = f"interface {self.name}"

        if self.include_superclasses:
            schema_def += f" extends {', '.join(self.include_superclasses)}"

        schema_def += f" {{\n{self.body}\n}}"

        if self.include_export:
            schema_def = f"export {schema_def}"

        return schema_def
