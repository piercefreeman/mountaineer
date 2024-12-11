from dataclasses import dataclass
from enum import Enum
from inspect import Parameter, signature
from types import UnionType
from typing import Any, Optional, Type, Union, get_type_hints
from pydantic import BaseModel, create_model
from fastapi.params import Body, Depends, Header, Param
from pydantic.fields import FieldInfo

from mountaineer.actions.fields import get_function_metadata
from mountaineer.controller import ControllerBase, get_client_functions_cls
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.render import RenderBase

# Base data structures
@dataclass
class FieldWrapper:
    name: str
    value: Union[type['ModelWrapper'], type['EnumWrapper'], type]
    required: bool

@dataclass
class ModelWrapper:
    model: type[BaseModel]
    isolated_model: type[BaseModel]  # Model with only direct fields
    superclasses: list['ModelWrapper']
    value_models: list[FieldWrapper]

@dataclass
class EnumWrapper:
    enum: type[Enum]

@dataclass
class ActionWrapper:
    params: list[FieldWrapper]
    headers: list[FieldWrapper]
    request_body: Optional[ModelWrapper]
    response_body: Optional[ModelWrapper]

@dataclass
class ControllerWrapper:
    actions: dict[str, ActionWrapper]  # {url: action}
    render: Optional[ModelWrapper]

# Helper functions
def is_pydantic_field_type(type_: type) -> bool:
    """Check if a type can be used as a Pydantic field"""
    from typing import get_origin
    return (
        type_ in (str, int, float, bool, bytes) or
        get_origin(type_) in (list, dict, tuple, set)
    )

def is_Union_type(type_: type) -> bool:
    """Check if a type is a Union type"""
    return (
        getattr(type_, "__origin__", None) is Union or
        isinstance(type_, UnionType)
    )

def get_Union_types(type_: type) -> list[type]:
    """Get the types from a Union type"""
    from typing import get_args
    return list(get_args(type_))

# Main parser class
class ControllerParser:
    def __init__(self):
        self.parsed_models: dict[type[BaseModel], ModelWrapper] = {}
        self.parsed_enums: dict[type[Enum], EnumWrapper] = {}

    def parse_controller(self, controller: type['ControllerBase']) -> ControllerWrapper:
        """Main entry point to parse a controller into intermediary representation"""
        # Get all valid superclasses in MRO order
        base_exclude = (RenderBase, ControllerBase, LayoutControllerBase)
        controller_classes = self._get_valid_mro_classes(controller, base_exclude)

        # Parse actions from all valid controller classes
        actions: dict[str, ActionWrapper] = {}
        for cls in controller_classes:
            cls_actions = self._parse_actions(cls)
            # Later classes override earlier ones if URLs conflict
            actions.update(cls_actions)

        # Get render model from the concrete controller
        render = self._parse_render(controller)

        return ControllerWrapper(
            actions=actions,
            render=render
        )

    def _parse_model(self, model: type[BaseModel]) -> ModelWrapper:
        """Parse a Pydantic model into ModelWrapper, handling inheritance"""
        # Return cached if already parsed
        if model in self.parsed_models:
            return self.parsed_models[model]

        # Get all valid superclasses in MRO order, excluding BaseModel and above
        model_classes = self._get_valid_mro_classes(model, (BaseModel,RenderBase))

        # Parse direct superclasses (excluding the model itself)
        superclasses: list[ModelWrapper] = []
        for base in model_classes[1:]:  # Skip the first class (model itself)
            if base not in self.parsed_models:
                # Create temporary empty wrapper to handle circular dependencies
                self.parsed_models[base] = ModelWrapper(
                    model=base,
                    isolated_model=base,  # Temporary
                    superclasses=[],      # Temporary
                    value_models=[]       # Temporary
                )
                # Now parse it properly
                self.parsed_models[base] = self._parse_model(base)
            superclasses.append(self.parsed_models[base])

        # Handle fields, excluding those from superclasses
        fields: list[FieldWrapper] = []
        superclass_fields = {
            name
            for superclass in superclasses
            for name in superclass.model.model_fields
        }

        isolated_model = self._create_isolated_model(model)
        for name, field in isolated_model.model_fields.items():
            fields.append(self._parse_field(name, field))

        wrapper = ModelWrapper(
            model=model,
            isolated_model=isolated_model,
            superclasses=superclasses,
            value_models=fields
        )
        self.parsed_models[model] = wrapper
        return wrapper

    def _parse_field(self, name: str, field: FieldInfo) -> FieldWrapper:
        """Parse a field into FieldWrapper, handling nested types"""
        field_type = field.annotation

        if is_Union_type(field_type):
            # For Unions, we need to handle each possible type
            Union_types = get_Union_types(field_type)
            # Use first non-None type as the base type
            base_type = next((t for t in Union_types if t is not type(None)), Union_types[0])
            field_type = base_type

        if isinstance(field_type, type):
            if issubclass(field_type, BaseModel):
                value = self._parse_model(field_type)
            elif issubclass(field_type, Enum):
                value = self._parse_enum(field_type)
            else:
                value = field_type
        else:
            # Handle other types like generics
            value = field_type

        return FieldWrapper(
            name=name,
            value=value,
            required=field.is_required()
        )

    def _parse_enum(self, enum_type: type[Enum]) -> EnumWrapper:
        """Parse an Enum into EnumWrapper"""
        if enum_type in self.parsed_enums:
            return self.parsed_enums[enum_type]

        wrapper = EnumWrapper(enum=enum_type)
        self.parsed_enums[enum_type] = wrapper
        return wrapper

    def _parse_actions(self, controller: type['ControllerBase']) -> dict[str, ActionWrapper]:
        """Parse all actions in a controller"""
        actions: dict[str, ActionWrapper] = {}

        for name, func, metadata in get_client_functions_cls(controller):
            action = ActionWrapper(
                params=self._parse_params(metadata),
                headers=self._parse_headers(metadata),
                request_body=self._parse_request_body(metadata),
                response_body=self._parse_response_body(metadata)
            )

            # TODO: We need a better way to get the url from the metadata for this particular
            # controller instance (if relevant)
            actions[name] = action
            #actions[metadata.url] = action

        return actions

    def _parse_render(self, controller: type['ControllerBase']) -> Optional[ModelWrapper]:
        """Parse the render method's return type"""
        render = getattr(controller, 'render', None)
        if not render:
            return None

        metadata = get_function_metadata(render)
        return_model = metadata.get_render_model()

        if not return_model:
            return None

        return self._parse_model(return_model)

    def _create_isolated_model(
        self,
        model: type[BaseModel],
    ) -> type[BaseModel]:
        """Create a new model with only the direct fields (no inherited fields)"""
        model_to_annotations = {}

        include_fields = {
            field_name: (field_info.annotation, field_info)
            for field_name, field_info in model.model_fields.items()
            if field_name in model.__dict__["__annotations__"]
        }

        # for mro_class in [model, *model.__mro__]:
        #     if issubclass(mro_class, BaseModel):
        #         model_to_annotations[mro_class] = {
        #             field: (field_info.annotation, field_info)
        #             for field, field_info in mro_class.model_fields.items()
        #             if not field_info.exclude
        #         }

        # main_definitions = model_to_annotations.pop(model)
        # superclass_definitions = {
        #     field: annotation
        #     for model, definitions in model_to_annotations.items()
        #     for field, (annotation, _) in definitions.items()
        # }

        # include_fields = {
        #     field: (annotation, field_info)
        #     for field, (annotation, field_info) in main_definitions.items()
        #     if (
        #         field not in superclass_definitions or superclass_definitions[field] != annotation
        #     )
        # }

        return create_model(
            model.__name__,
            __config__=model.model_config,
            **include_fields,  # type: ignore
        )

    def _parse_params(self, metadata) -> list[FieldWrapper]:
        """Parse route parameters by examining function signature and decorators"""
        params: list[FieldWrapper] = []
        sig = signature(metadata.function)
        type_hints = get_type_hints(metadata.function)

        for param_name, param in sig.parameters.items():
            # Skip *args and **kwargs
            if param.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
                continue

            # Get param type and annotation metadata
            param_type = type_hints.get(param_name, Any)
            field_info = param.default if isinstance(param.default, Param) else Param()

            # Skip dependency injected params
            if isinstance(field_info, Depends):
                continue

            # Only include route params (not body, headers etc)
            if not isinstance(field_info, (Body, Header)):
                field = self._create_field_from_param(
                    name=param_name,
                    type_=param_type,
                    required=param.default == Parameter.empty,
                    field_info=field_info
                )
                params.append(field)

        return params

    def _parse_headers(self, metadata) -> list[FieldWrapper]:
        """Parse header parameters from function signature"""
        headers: list[FieldWrapper] = []
        sig = signature(metadata.function)
        type_hints = get_type_hints(metadata.function)

        for param_name, param in sig.parameters.items():
            if isinstance(param.default, Header):
                field = self._create_field_from_param(
                    name=param_name,
                    type_=type_hints.get(param_name, Any),
                    required=param.default.default == Parameter.empty,
                    field_info=param.default
                )
                headers.append(field)

        return headers

    def _parse_request_body(self, metadata) -> Optional[ModelWrapper]:
        """Parse request body model from function signature"""
        sig = signature(metadata.function)
        type_hints = get_type_hints(metadata.function)

        for param_name, param in sig.parameters.items():
            if isinstance(param.default, Body):
                param_type = type_hints.get(param_name, Any)
                if isinstance(param_type, type) and issubclass(param_type, BaseModel):
                    return self._parse_model(param_type)
                elif is_pydantic_field_type(param_type):
                    # Handle primitive types wrapped in Body()
                    return self._create_wrapper_model(param_type, param_name)

        return None

    def _parse_response_body(self, metadata) -> Optional[ModelWrapper]:
        """Parse response model from return type annotation"""
        return_type = get_type_hints(metadata.function).get('return', None)
        if return_type and isinstance(return_type, type) and issubclass(return_type, BaseModel):
            return self._parse_model(return_type)
        return None

    def _create_field_from_param(
        self,
        name: str,
        type_: type,
        required: bool,
        field_info: Param
    ) -> FieldWrapper:
        """Create a FieldWrapper from a parameter's information"""
        if isinstance(type_, type):
            if issubclass(type_, BaseModel):
                value = self._parse_model(type_)
            elif issubclass(type_, Enum):
                value = self._parse_enum(type_)
            else:
                value = type_
        else:
            value = type_

        return FieldWrapper(
            name=name,
            value=value,
            required=required
        )

    def _create_wrapper_model(self, field_type: type, field_name: str) -> ModelWrapper:
        """Create a single-field model wrapper for primitive body types"""
        model = create_model(
            f"{field_name.title()}Body",
            **{field_name: (field_type, ...)}
        )
        return self._parse_model(model)

    def _get_valid_mro_classes(self, cls: type, base_exclude_classes: tuple[type, ...]) -> list[type]:
        """Helper to get valid MRO classes, excluding certain base classes and anything above them"""
        mro = []
        for base in cls.__mro__:
            # Stop when we hit any of the excluded base classes
            if base in base_exclude_classes:
                break
            # Skip object() as well
            if base is object:
                continue
            mro.append(base)
        return mro
