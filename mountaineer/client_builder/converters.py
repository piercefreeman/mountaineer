from dataclasses import dataclass
from typing import Any, Dict, List, Union

from graphlib import TopologicalSorter

from mountaineer.actions.fields import FunctionActionType
from mountaineer.client_builder.parser import (
    ActionWrapper,
    ControllerWrapper,
    EnumWrapper,
    FieldWrapper,
    ModelWrapper,
)
from mountaineer.client_builder.types import (
    DictOf,
    ListOf,
    Or,
    SetOf,
    TupleOf,
    TypeDefinition,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)
from mountaineer.logging import LOGGER


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


class BaseTypeScriptConverter:
    """Base class for TypeScript conversion with shared type conversion logic"""

    def _get_field_type(self, field: FieldWrapper) -> str:
        return self._get_annotated_value(field.value)

    def _get_annotated_value(self, value):
        """Convert a field type to TypeScript type."""
        if isinstance(value, ModelWrapper):
            return value.model.__name__
        elif isinstance(value, EnumWrapper):
            return value.enum.__name__
        else:
            complex_value = self._handle_complex_type(value, requires_complex=True)
            if complex_value:
                return complex_value
            primitive_value = self._map_primitive_type_to_typescript(value)
            if primitive_value:
                return primitive_value
            return "any"

    def _map_primitive_type_to_typescript(self, py_type: type) -> str | None:
        """Map Python types to TypeScript types"""
        type_map = {
            str: "string",
            int: "number",
            float: "number",
            bool: "boolean",
            None: "null",
        }
        return type_map.get(py_type)

    def _handle_complex_type(
        self, type_hint: Any, requires_complex: bool = False
    ) -> str | None:
        """Handle complex type hints like List[str], Dict[str, int], etc."""
        if not isinstance(type_hint, TypeDefinition):
            return None

        if isinstance(type_hint, ListOf):
            return f"Array<{self._get_annotated_value(type_hint.type)}>"

        if isinstance(type_hint, TupleOf):
            return f"Array<{self._get_annotated_value(Or(type_hint.types))}>"

        if isinstance(type_hint, SetOf):
            return f"Set<{self._get_annotated_value(type_hint.type)}>"

        if isinstance(type_hint, DictOf):
            return f"Record<{self._get_annotated_value(type_hint.key_type)}, {self._get_field_type(type_hint.value_type)}>"

        if isinstance(type_hint, Or):
            non_null_types = [t for t in type_hint.children if t != type(None)]  # noqa: E721
            if len(non_null_types) == 1:
                return self._get_annotated_value(non_null_types[0])
            return " | ".join(self._get_annotated_value(t) for t in non_null_types)

        return "any"


class TypeScriptActionConverter(BaseTypeScriptConverter):
    """Converts controller actions to TypeScript"""

    def convert_action(
        self, name: str, action: ActionWrapper, url_prefix: str = ""
    ) -> TypescriptAction:
        """Convert an action to TypeScript"""
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

        request_payload = self._build_request_payload(
            url_prefix + f"/{name}", action, parameters_dict
        )

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
            "method": "POST",
            "url": url,
            "path": {},
            "query": {},
            "signal": TSLiteral("signal"),
        }

        for param in action.params:
            if param.name in parameters:
                payload["query"][param.name] = TSLiteral(param.name)

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

        if getattr(action.response_body.model, "is_stream", False):
            return f"Promise<AsyncGenerator<{response_type}, void, unknown>>"

        return f"Promise<{response_type}>"


class TypeScriptSchemaConverter(BaseTypeScriptConverter):
    """Converts models and enums to TypeScript types"""

    def __init__(self, export_interface: bool = False):
        super().__init__()
        self.export_interface = export_interface
        self.generated_schemas = {}

    def convert_model(self, model: ModelWrapper) -> TypescriptSchema:
        """Convert a model to a TypeScript interface"""
        if model.model.__name__ in self.generated_schemas:
            return None

        # Process superclasses first
        for superclass in model.superclasses:
            self.convert_model(superclass)

        fields: list[str] = []
        for field in model.value_models:
            field_type = self._get_field_type(field)
            fields.append(
                f"  {field.name}{'?' if not field.required else ''}: {field_type};"
            )

        schema = TypescriptSchema(
            interface_type="interface",
            name=model.model.__name__,
            body="\n".join(fields),
            include_export=self.export_interface,
            include_superclasses=[s.model.__name__ for s in model.superclasses],
        )

        self.generated_schemas[model.model.__name__] = schema
        return schema

    def convert_enum(self, enum: EnumWrapper) -> TypescriptSchema:
        """Convert an enum to a TypeScript enum"""
        if enum.enum.__name__ in self.generated_schemas:
            return None

        fields = []
        for name, value in enum.enum.__members__.items():
            if isinstance(value.value, (int, float)):
                fields.append(f"  {name} = {value.value},")
            else:
                fields.append(f'  {name} = "{value.value}",')

        schema = TypescriptSchema(
            interface_type="enum",
            name=enum.enum.__name__,
            body="\n".join(fields),
            include_export=self.export_interface,
        )

        self.generated_schemas[enum.enum.__name__] = schema
        return schema

    def _process_model_dependencies(self, model: ModelWrapper) -> None:
        """Process all enum fields and nested models within a model"""
        for field in model.value_models:
            if isinstance(field.value, EnumWrapper):
                self.convert_enum(field.value)
            elif isinstance(field.value, ModelWrapper):
                self.convert_model(field.value)
                self._process_model_dependencies(field.value)


class TypeScriptLinkConverter(BaseTypeScriptConverter):
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


class TypeScriptServerHookConverter(BaseTypeScriptConverter):
    """Converts controllers to TypeScript server hooks"""

    def convert_controller_hooks(
        self,
        controller: ControllerWrapper,
        controller_id: str,
    ) -> str:
        """Generate useServer hook for a controller"""
        if not controller.render:
            return ""

        render_model = controller.render.model.__name__

        imports = self._generate_imports(controller, controller_id, render_model)
        interface = self._generate_interface(render_model, controller_id)
        hook = self._generate_hook(controller, controller_id, render_model)

        return "\n\n".join(["\n".join(imports), "\n".join(interface), "\n".join(hook)])

    def _generate_imports(
        self, controller: ControllerWrapper, controller_id: str, render_model: str
    ) -> list[str]:
        """Generate import statements"""
        imports = [
            "import React, { useState } from 'react';",
            "import { applySideEffect } from '../api';",
            "import LinkGenerator from '../links';",
            f"import {{ {render_model}, {controller_id} }} from './models';",
        ]

        if controller.all_actions:
            action_imports = [
                f"import {{ {', '.join(action.name for action in controller.all_actions)} }} from './actions';"
            ]
            imports.extend(action_imports)

        return imports

    def _generate_interface(self, render_model: str, controller_id: str) -> list[str]:
        """Generate ServerState interface"""
        return [
            f"export interface ServerState extends {render_model}, {controller_id} {{",
            "  linkGenerator: typeof LinkGenerator;",
            "}",
        ]

    def _generate_hook(
        self, controller: ControllerWrapper, controller_id: str, render_model: str
    ) -> list[str]:
        """Generate useServer hook implementation"""
        server_response = {
            TSLiteral("...serverState"): TSLiteral("...serverState"),
            "linkGenerator": TSLiteral("LinkGenerator"),
        }

        for action in controller.all_actions:
            server_response[TSLiteral(action.name)] = (
                TSLiteral(f"applySideEffect({action.name}, setControllerState)")
                if action.action_type == FunctionActionType.SIDEEFFECT
                else TSLiteral(action.name)
            )

        response_body = python_payload_to_typescript(server_response)

        return [
            "export const useServer = () : ServerState => {",
            f"  const [serverState, setServerState] = useState(SERVER_DATA['{controller_id}'] as {render_model});",
            "",
            f"  return {response_body}",
            "};",
        ]


class TypeScriptControllerConverter(BaseTypeScriptConverter):
    """Converts controllers to TypeScript interfaces"""

    def __init__(self, action_converter: TypeScriptActionConverter):
        super().__init__()
        self.action_converter = action_converter

    def convert_controller(
        self, controller_id: str, wrapper: ControllerWrapper, url_prefix: str = ""
    ) -> TypescriptSchema:
        """Convert a controller to a TypeScript interface"""
        fields: list[str] = []

        # Convert each action
        for name, action in wrapper.actions.items():
            action_def = self.action_converter.convert_action(name, action, url_prefix)
            fields.append(
                f"  {action_def.name}: ({action_def.parameters}) => {action_def.response_type};"
            )

        return TypescriptSchema(
            interface_type="interface",
            name=controller_id,
            body="\n".join(fields),
            include_export=True,
            include_superclasses=[s.__class__.__name__ for s in wrapper.superclasses],
        )


class TypeScriptGenerator:
    """Main class for generating TypeScript definitions with separated dependency handling"""

    def __init__(self, export_interface: bool = True):
        self.schema_converter = TypeScriptSchemaConverter(export_interface)
        self.action_converter = TypeScriptActionConverter()
        self.controller_converter = TypeScriptControllerConverter(self.action_converter)

    def generate_definitions(
        self, parsed_controllers: Dict[str, "ParsedController"]
    ) -> str:
        """Generate all TypeScript definitions in dependency order"""
        # Get all controllers
        controllers = self._gather_all_controllers(
            [controller.wrapper for controller in parsed_controllers.values()]
        )

        # Collect all models and enums
        models, enums = self._gather_models_and_enums(controllers)

        # Build both graphs
        model_enum_sorter = self._build_model_enum_graph(models, enums)
        controller_sorter = self._build_controller_graph(controllers)

        # Generate schemas in order
        schemas: List[str] = []

        # First process models and enums in dependency order
        for item in model_enum_sorter:
            if isinstance(item, ModelWrapper):
                schema = self.schema_converter.convert_model(item)
            else:  # EnumWrapper
                schema = self.schema_converter.convert_enum(item)
            if schema:
                schemas.append(schema.to_js())

        # Then process controllers in dependency order
        for controller in controller_sorter:
            controller_schema = self.controller_converter.convert_controller(
                controller.name, controller
            )
            schemas.append(controller_schema.to_js())

        return "\n\n".join(schemas)

    def _build_model_enum_graph(
        self, models: List[ModelWrapper], enums: List[EnumWrapper]
    ):
        """Build dependency graph for models and enums"""
        # Build id-based graph
        graph: Dict[int, Set[int]] = {}
        id_to_obj: Dict[int, Union[ModelWrapper, EnumWrapper]] = {}

        # Initialize graph entries for all models and enums
        for model in models:
            graph[id(model)] = set()
            id_to_obj[id(model)] = model

        for enum in enums:
            graph[id(enum)] = set()
            id_to_obj[id(enum)] = enum

        # Add model superclass dependencies
        for model in models:
            graph[id(model)].update(id(superclass) for superclass in model.superclasses)

            # Add field dependencies
            for field in model.value_models:
                if isinstance(field.value, (ModelWrapper, EnumWrapper)):
                    graph[id(model)].add(id(field.value))

        # Convert graph to use actual objects for TopologicalSorter
        sorted_ids = TopologicalSorter(graph).static_order()
        return [id_to_obj[node_id] for node_id in sorted_ids]

    def _build_controller_graph(
        self, controllers: List[ControllerWrapper]
    ) -> TopologicalSorter:
        """Build dependency graph for controllers"""
        # Build id-based graph
        graph: Dict[int, Set[int]] = {}
        id_to_obj: Dict[int, ControllerWrapper] = {}

        # Initialize graph entries for all controllers
        for controller in controllers:
            graph[id(controller)] = set()
            id_to_obj[id(controller)] = controller

        # Add controller superclass dependencies
        for controller in controllers:
            graph[id(controller)].update(
                id(superclass) for superclass in controller.superclasses
            )

        # Convert graph to use actual objects for TopologicalSorter
        sorted_ids = TopologicalSorter(graph).static_order()
        return [id_to_obj[node_id] for node_id in sorted_ids]

    def _gather_all_controllers(
        self, controllers: List[ControllerWrapper]
    ) -> List[ControllerWrapper]:
        """Gather all controllers including superclasses"""
        seen_ids = set()
        result = []

        def gather(controller: ControllerWrapper) -> None:
            if id(controller) not in seen_ids:
                seen_ids.add(id(controller))
                for superclass in controller.superclasses:
                    gather(superclass)
                result.append(controller)

        for controller in controllers:
            gather(controller)

        return result

    def _gather_models_and_enums(
        self, controllers: List[ControllerWrapper]
    ) -> tuple[List[ModelWrapper], List[EnumWrapper]]:
        """Collect all unique models and enums from controllers"""
        models_dict: Dict[int, ModelWrapper] = {}
        enums_dict: Dict[int, EnumWrapper] = {}

        def process_value(value):
            if isinstance(value, ModelWrapper):
                process_model(value)
            elif isinstance(value, EnumWrapper):
                enums_dict[id(value)] = value
            elif isinstance(value, TypeDefinition):
                for child in value.children:
                    process_value(child)
            else:
                LOGGER.info(f"Non-complex value: {value}")

        def process_model(model: ModelWrapper) -> None:
            """Process a model and all its dependencies"""
            if id(model) not in models_dict:
                models_dict[id(model)] = model
                # Process all fields
                for field in model.value_models:
                    process_value(field.value)
                # Process superclasses
                for superclass in model.superclasses:
                    process_model(superclass)

        # Process all models from controllers
        for controller in controllers:
            if controller.render:
                process_model(controller.render)
            for action in controller.actions.values():
                if action.request_body:
                    process_model(action.request_body)
                if action.response_body:
                    process_model(action.response_body)

        return list(models_dict.values()), list(enums_dict.values())
