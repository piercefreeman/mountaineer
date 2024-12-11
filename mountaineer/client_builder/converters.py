from dataclasses import dataclass
from typing import Any

from inflection import camelize

from mountaineer.client_builder.parser import (
    ActionWrapper,
    ControllerWrapper,
    EnumWrapper,
    FieldWrapper,
    ModelWrapper,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)


@dataclass
class TypescriptAction:
    """Represents a TypeScript action function"""

    name: str
    parameters: str
    typehints: str
    default_parameters: str | None
    response_type: str
    body: str
    required_models: list[str]

    def to_js(self) -> str:
        script = f"export const {self.name} = ({self.parameters} : {self.typehints}"
        if self.default_parameters:
            script += f" = {self.default_parameters}"
        script += f"): {self.response_type} => {{ {self.body} }}"
        return script


@dataclass
class TypescriptError:
    """Represents a TypeScript error class"""

    name: str
    base_name: str
    required_models: list[str]

    def to_js(self) -> str:
        return f"export class {self.name} extends FetchErrorBase<{self.base_name}> {{}}"


@dataclass
class TypescriptSchema:
    """Represents a TypeScript interface or enum"""

    interface_type: str  # "interface" or "enum"
    name: str
    body: str
    include_export: bool
    include_superclasses: list[str] = None

    def to_js(self) -> str:
        schema_def = f"{self.interface_type} {self.name}"

        if self.include_superclasses:
            schema_def += f" extends {', '.join(self.include_superclasses)}"

        schema_def += f" {{\n{self.body}\n}}"

        if self.include_export:
            schema_def = f"export {schema_def}"

        return schema_def


class TypeScriptActionConverter:
    """Converts controller actions to TypeScript"""

    def convert_action(
        self, name: str, action: ActionWrapper, url_prefix: str = ""
    ) -> TypescriptAction:
        """Convert an action to TypeScript"""
        # Build parameters
        parameters_dict: dict[str, Any] = {}
        typehint_dict: dict[str, Any] = {}
        required_models: list[str] = []

        # System parameters (always optional)
        system_parameters = {"signal": TSLiteral("signal")}
        system_typehints = {TSLiteral("signal?"): TSLiteral("AbortSignal")}

        # Add path/query parameters
        for param in action.params:
            parameters_dict[param.name] = TSLiteral(param.name)
            typehint_dict[
                TSLiteral(f"{param.name}{'?' if not param.required else ''}")
            ] = self._get_field_type(param)

        # Add request body if present
        if action.request_body:
            model_name = action.request_body.model.__name__
            parameters_dict["requestBody"] = TSLiteral("requestBody")
            typehint_dict[TSLiteral("requestBody")] = TSLiteral(model_name)
            required_models.append(model_name)

        # Merge system parameters
        has_nonsystem_parameters = bool(parameters_dict)
        parameters_dict.update(system_parameters)
        typehint_dict.update(system_typehints)

        # Build request payload
        request_payload = self._build_request_payload(
            url_prefix + f"/{name}", action, parameters_dict
        )

        # Determine response type
        response_type = self._get_response_type(action)
        if action.response_body:
            required_models.append(action.response_body.model.__name__)

        return TypescriptAction(
            name=name,
            parameters=python_payload_to_typescript(parameters_dict),
            typehints=python_payload_to_typescript(typehint_dict),
            default_parameters=None if has_nonsystem_parameters else "{}",
            response_type=response_type,
            body=f"return __request({request_payload});",
            required_models=required_models,
        )

    def _build_request_payload(
        self, url: str, action: ActionWrapper, parameters: dict[str, Any]
    ) -> str:
        payload: dict[str, Any] = {
            "method": "POST",  # Default to POST for actions
            "url": url,
            "path": {},
            "query": {},
            "signal": TSLiteral("signal"),
        }

        # Add parameters
        for param in action.params:
            if param.name in parameters:
                payload["query"][param.name] = TSLiteral(param.name)

        # Add request body
        if action.request_body:
            payload["body"] = TSLiteral("requestBody")
            payload["mediaType"] = "application/json"

        # Clean up empty dicts
        for key in ["path", "query"]:
            if not payload[key]:
                del payload[key]

        return python_payload_to_typescript(payload)

    def _get_response_type(self, action: ActionWrapper) -> str:
        if not action.response_body:
            return "Promise<void>"

        response_type = action.response_body.model.__name__

        # Handle streaming responses
        if getattr(action.response_body.model, "is_stream", False):
            return f"Promise<AsyncGenerator<{response_type}, void, unknown>>"

        return f"Promise<{response_type}>"

    def _get_field_type(self, field: FieldWrapper) -> str:
        """Convert a field type to TypeScript type.

        Args:
            field: The FieldWrapper instance containing type information

        Returns:
            str: The corresponding TypeScript type
        """
        if isinstance(field.value, ModelWrapper):
            return field.value.model.__name__
        elif isinstance(field.value, EnumWrapper):
            return field.value.enum.__name__
        elif isinstance(field.value, type):
            # Handle basic Python types
            type_map = {
                str: "string",
                int: "number",
                float: "number",
                bool: "boolean",
                dict: "Record<string, any>",
                list: "Array<any>",
                None: "null",
            }
            return type_map.get(field.value, "any")
        else:
            # Handle complex types (List, Dict, etc.)
            import typing

            origin = typing.get_origin(field.value)
            args = typing.get_args(field.value)

            if origin == list or origin == typing.List:
                if not args:
                    return "Array<any>"
                return f"Array<{self._get_field_type(FieldWrapper('', args[0], True))}>"

            elif origin == dict or origin == typing.Dict:
                if not args:
                    return "Record<string, any>"
                key_type = self._get_field_type(FieldWrapper('', args[0], True))
                value_type = self._get_field_type(FieldWrapper('', args[1], True))
                return f"Record<{key_type}, {value_type}>"

            elif origin == typing.Union:
                # Handle Optional types (Union[Type, None])
                types = [t for t in args if t != type(None)]  # noqa: E721
                if len(types) == 1:
                    return self._get_field_type(FieldWrapper('', types[0], True))
                return " | ".join(self._get_field_type(FieldWrapper('', t, True)) for t in types)

            elif origin == typing.Literal:
                # Handle Literal types
                literal_values = args
                if all(isinstance(val, str) for val in literal_values):
                    return " | ".join(f"'{val}'" for val in literal_values)
                return " | ".join(str(val) for val in literal_values)

            # For any other complex types, return 'any'
            return "any"

class TypeScriptSchemaConverter:
    """Converts models to TypeScript interfaces/enums"""

    def __init__(self, export_interface: bool = False):
        self.export_interface = export_interface

    def convert_model(self, model: ModelWrapper) -> TypescriptSchema:
        """Convert a model to a TypeScript interface"""
        fields: list[str] = []

        for field in model.value_models:
            field_type = self._get_field_type(field)

            fields.append(
                f"  {field.name}{'?' if not field.required else ''}: {field_type};"
            )

        return TypescriptSchema(
            interface_type="interface",
            name=model.model.__name__,
            body="\n".join(fields),
            include_export=self.export_interface,
            include_superclasses=[s.model.__name__ for s in model.superclasses],
        )

    def convert_enum(self, enum: EnumWrapper) -> TypescriptSchema:
        """Convert an enum to a TypeScript enum"""
        fields: dict[str, Any] = {}

        for name, value in enum.enum.__members__.items():
            if isinstance(value.value, (int, float)):
                key = f"Value__{value.value}"
            else:
                key = camelize(str(value.value), uppercase_first_letter=True)

            fields[TSLiteral(key)] = value.value

        # Convert to enum format
        enum_body = python_payload_to_typescript(fields).replace(":", " =")

        return TypescriptSchema(
            interface_type="enum",
            name=enum.enum.__name__,
            body=enum_body.strip().lstrip("{").rstrip("}"),
            include_export=self.export_interface,
        )

    def _get_field_type(self, field: FieldWrapper) -> str:
        """Convert a field type to TypeScript type"""
        if isinstance(field.value, ModelWrapper):
            return field.value.model.__name__
        elif isinstance(field.value, EnumWrapper):
            return field.value.enum.__name__
        elif isinstance(field.value, type):
            # Handle basic Python types
            return self._map_python_type_to_typescript(field.value)
        else:
            # Handle complex types (List, Dict, etc)
            return self._handle_complex_type(field.value)

    def _map_python_type_to_typescript(self, py_type: type) -> str:
        """Map Python types to TypeScript types"""
        type_map = {
            str: "string",
            int: "number",
            float: "number",
            bool: "boolean",
            dict: "Record<string, any>",
            list: "Array<any>",
            None: "null",
        }
        return type_map.get(py_type, "any")

    def _handle_complex_type(self, type_hint: Any) -> str:
        """Handle complex type hints like List[str], Dict[str, int], etc"""
        # This would need to be implemented based on your typing needs
        # For now, return a basic type
        return "any"


class TypeScriptLinkConverter:
    """Converts controller routes to TypeScript link generators"""

    def convert_controller_links(
        self, controller: ControllerWrapper, url_prefix: str = ""
    ) -> str:
        """Generate link formatter for a controller's routes"""
        if not controller.render:
            return ""

        # Collect parameters from render model
        parameters: dict[str, Any] = {}
        typehints: dict[str, Any] = {}

        for field in controller.render.value_models:
            if field.required:  # Only include required fields as URL parameters
                parameters[field.name] = TSLiteral(field.name)
                typehints[TSLiteral(field.name)] = self._get_field_type(field)

        # Generate the link function
        return self._generate_link_function(url_prefix, parameters, typehints)

    def _generate_link_function(
        self, url_prefix: str, parameters: dict[str, Any], typehints: dict[str, Any]
    ) -> str:
        param_str = python_payload_to_typescript(parameters)
        typehint_str = python_payload_to_typescript(typehints)

        return f"""export const getLink = ({param_str} : {typehint_str}) => {{
  const url = '{url_prefix}';
  const queryParameters = {param_str};
  return __getLink({{
    rawUrl: url,
    queryParameters,
    pathParameters: {{}}
  }});
}};"""

    def _get_field_type(self, field: FieldWrapper) -> str:
        """Get TypeScript type for a field"""
        if isinstance(field.value, ModelWrapper):
            return field.value.model.__name__
        elif isinstance(field.value, EnumWrapper):
            return field.value.enum.__name__
        elif isinstance(field.value, type):
            return self._map_python_type_to_typescript(field.value)
        else:
            return "any"

    def _map_python_type_to_typescript(self, py_type: type) -> str:
        """Map Python types to TypeScript types"""
        type_map = {
            str: "string",
            int: "number",
            float: "number",
            bool: "boolean",
        }
        return type_map.get(py_type, "any")
