from dataclasses import dataclass
from enum import Enum
from types import UnionType
from typing import Callable, Optional, Union

from fastapi import APIRouter
from fastapi.params import Body, Depends, Header, Param
from fastapi.routing import APIRoute
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from mountaineer.actions.fields import get_function_metadata
from mountaineer.annotation_helpers import MountaineerUnsetValue
from mountaineer.controller import ControllerBase, get_client_functions_cls
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.render import RenderBase


# Base data structures
@dataclass
class FieldWrapper:
    name: str
    value: Union[type["ModelWrapper"], type["EnumWrapper"], type]
    required: bool


@dataclass
class ModelWrapper:
    model: type[BaseModel]
    isolated_model: type[BaseModel]  # Model with only direct fields
    superclasses: list["ModelWrapper"]
    value_models: list[FieldWrapper]


@dataclass
class EnumWrapper:
    enum: type[Enum]


@dataclass
class ActionWrapper:
    name: str
    params: list[FieldWrapper]
    headers: list[FieldWrapper]
    request_body: Optional[ModelWrapper]
    response_body: Optional[ModelWrapper]


@dataclass
class ControllerWrapper:
    superclasses: list["ControllerWrapper"]
    actions: dict[str, ActionWrapper]  # {url: action} directly implemented for this controller
    render: Optional[ModelWrapper]


# Helper functions
def is_pydantic_field_type(type_: type) -> bool:
    """Check if a type can be used as a Pydantic field"""
    from typing import get_origin

    return type_ in (str, int, float, bool, bytes) or get_origin(type_) in (
        list,
        dict,
        tuple,
        set,
    )


def is_Union_type(type_: type) -> bool:
    """Check if a type is a Union type"""
    return getattr(type_, "__origin__", None) is Union or isinstance(type_, UnionType)


def get_Union_types(type_: type) -> list[type]:
    """Get the types from a Union type"""
    from typing import get_args

    return list(get_args(type_))


# Main parser class
class ControllerParser:
    def __init__(self):
        self.parsed_models: dict[type[BaseModel], ModelWrapper] = {}
        self.parsed_enums: dict[type[Enum], EnumWrapper] = {}
        self.parsed_controllers: dict[type[ControllerBase], ControllerWrapper] = {}

    def parse_controller(self, controller: type[ControllerBase]) -> ControllerWrapper:
        """Main entry point to parse a controller into intermediary representation"""
        if controller in self.parsed_controllers:
            return self.parsed_controllers[controller]

        # Get all valid superclasses in MRO order
        base_exclude = (RenderBase, ControllerBase, LayoutControllerBase)
        controller_classes = self._get_valid_mro_classes(controller, base_exclude)

        # Get render model from the concrete controller
        render = self._parse_render(controller)
        actions = self._parse_actions(controller)

        # Parse superclasses
        superclass_controllers : list[ControllerWrapper] = []
        for superclass in controller_classes[1:]:
            superclass_controllers.append(
                self.parse_controller(superclass)
            )

        return ControllerWrapper(actions=actions, render=render, superclasses=superclass_controllers)

    def _parse_model(self, model: type[BaseModel]) -> ModelWrapper:
        """Parse a Pydantic model into ModelWrapper, handling inheritance"""
        # Return cached if already parsed
        if model in self.parsed_models:
            return self.parsed_models[model]

        # Get all valid superclasses in MRO order, excluding BaseModel and above
        model_classes = self._get_valid_mro_classes(model, (BaseModel, RenderBase))

        # Parse direct superclasses (excluding the model itself)
        superclasses: list[ModelWrapper] = []
        for base in model_classes[1:]:  # Skip the first class (model itself)
            if base not in self.parsed_models:
                # Now parse it properly
                self.parsed_models[base] = self._parse_model(base)
            superclasses.append(self.parsed_models[base])

        # Handle fields, excluding those from superclasses
        fields: list[FieldWrapper] = []
        isolated_model = self._create_isolated_model(model)
        for name, field in isolated_model.model_fields.items():
            fields.append(self._parse_field(name, field))

        wrapper = ModelWrapper(
            model=model,
            isolated_model=isolated_model,
            superclasses=superclasses,
            value_models=fields,
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
            base_type = next(
                (t for t in Union_types if t is not type(None)), Union_types[0]
            )
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

        return FieldWrapper(name=name, value=value, required=field.is_required())

    def _parse_enum(self, enum_type: type[Enum]) -> EnumWrapper:
        """Parse an Enum into EnumWrapper"""
        if enum_type in self.parsed_enums:
            return self.parsed_enums[enum_type]

        wrapper = EnumWrapper(enum=enum_type)
        self.parsed_enums[enum_type] = wrapper
        return wrapper

    def _parse_render(
        self, controller: type[ControllerBase]
    ) -> Optional[ModelWrapper]:
        """Parse the render method's return type"""
        render = getattr(controller, "render", None)
        if not render:
            return None

        try:
            metadata = get_function_metadata(render)
        except AttributeError:
            return None

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

        return create_model(
            model.__name__,
            __config__=model.model_config,
            **include_fields,  # type: ignore
        )

    def _create_temp_route(self, func: Callable, name: str) -> APIRoute:
        """Create a temporary FastAPI route using the actual function"""
        router = APIRouter()
        router.add_api_route(
            path=f"/{name}",
            endpoint=func,
        )

        route = next(
            route
            for route in router.routes
            if isinstance(route, APIRoute) and route.path == f"/{name}"
        )

        return route

    def _parse_params(self, func: Callable, name: str) -> list[FieldWrapper]:
        """Parse route parameters using FastAPI's dependency system"""
        route = self._create_temp_route(func, name)
        params: list[FieldWrapper] = []

        for param in route.dependant.path_params:
            field = self._create_field_from_param(
                name=param.name,
                type_=param.type_,
                required=param.required,
                field_info=param.field_info if hasattr(param, "field_info") else None,
            )
            params.append(field)

        for param in route.dependant.query_params:
            if not isinstance(param.field_info, (Body, Header, Depends)):
                field = self._create_field_from_param(
                    name=param.name,
                    type_=param.type_,
                    required=param.required,
                    field_info=param.field_info
                    if hasattr(param, "field_info")
                    else None,
                )
                params.append(field)

        return params

    def _parse_headers(self, func: Callable, name: str) -> list[FieldWrapper]:
        """Parse header parameters using FastAPI's dependency system"""
        route = self._create_temp_route(func, name)
        headers: list[FieldWrapper] = []

        for param in route.dependant.header_params:
            field = self._create_field_from_param(
                name=param.name,
                type_=param.type_,
                required=param.required,
                field_info=param.field_info if hasattr(param, "field_info") else None,
            )
            headers.append(field)

        return headers

    def _parse_request_body(self, func: Callable, name: str) -> Optional[ModelWrapper]:
        """Parse request body using FastAPI's dependency system"""
        route = self._create_temp_route(func, name)

        if route.dependant.body_params:
            body_param = route.dependant.body_params[0]  # Get first body param
            if isinstance(body_param.type_, type) and issubclass(
                body_param.type_, BaseModel
            ):
                return self._parse_model(body_param.type_)
            elif is_pydantic_field_type(body_param.type_):
                return self._create_wrapper_model(body_param.type_, body_param.name)

        return None

    def _parse_response_body(
        self, metadata: "FunctionMetadata"
    ) -> Optional[ModelWrapper]:
        """Parse response model from metadata"""
        if not isinstance(metadata.return_model, MountaineerUnsetValue):
            model = metadata.get_return_model()
            if issubclass(model, BaseModel):
                return self._parse_model(model)
        return None

    def _parse_actions(
        self, controller: type[ControllerBase]
    ) -> dict[str, ActionWrapper]:
        """Parse all actions in a controller"""
        actions: dict[str, ActionWrapper] = {}

        for name, func, metadata in get_client_functions_cls(controller):
            print("parse actions", controller.__name__, name)
            action = ActionWrapper(
                name=name,
                params=self._parse_params(func, name),
                headers=self._parse_headers(func, name),
                request_body=self._parse_request_body(func, name),
                response_body=self._parse_response_body(metadata),
            )
            actions[name] = action

        return actions

    def _create_field_from_param(
        self, name: str, type_: type, required: bool, field_info: Param
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

        return FieldWrapper(name=name, value=value, required=required)

    def _create_wrapper_model(self, field_type: type, field_name: str) -> ModelWrapper:
        """Create a single-field model wrapper for primitive body types"""
        model = create_model(
            f"{field_name.title()}Body", **{field_name: (field_type, ...)}
        )
        return self._parse_model(model)

    def _get_valid_mro_classes(
        self, cls: type, base_exclude_classes: tuple[type, ...]
    ) -> list[type]:
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
