from dataclasses import dataclass

from mountaineer.client_builder.interface_builders.base import InterfaceBase
from mountaineer.client_builder.parser import (
    EnumWrapper,
)


@dataclass
class ModelInterface(InterfaceBase):
    name: str
    body: str
    include_superclasses: list[str]
    include_export: bool = True

    def from_model(self, value: ModelWrapper):
        fields: list[str] = []
        for field in model.value_models:
            field_type = self._get_field_type(field)
            fields.append(
                f"  {field.name}{'?' if not field.required else ''}: {field_type};"
            )

        schema = TypescriptSchema(
            interface_type="interface",
            name=model.name,
            body="\n".join(fields),
            include_export=self.export_interface,
            include_superclasses=[s.name for s in model.superclasses],
        )
        return schema

    def to_js(self) -> str:
        schema_def = f"interface {self.name}"

        if self.include_superclasses:
            schema_def += f" extends {', '.join(self.include_superclasses)}"

        schema_def += f" {{\n{self.body}\n}}"

        if self.include_export:
            schema_def = f"export {schema_def}"

        return schema_def
