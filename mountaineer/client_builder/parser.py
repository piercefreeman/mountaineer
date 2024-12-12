from copy import copy
from dataclasses import dataclass
from enum import Enum
from inspect import isclass
from typing import (
    Callable,
    Generator,
    Optional,
    Type,
    TypeVar,
    Union,
)

from fastapi import APIRouter
from fastapi.params import Body, Depends, Header
from fastapi.routing import APIRoute
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from mountaineer.actions.fields import (
    FunctionActionType,
    FunctionMetadata,
    get_function_metadata,
)
from mountaineer.annotation_helpers import MountaineerUnsetValue
from mountaineer.client_builder.types import TypeDefinition, TypeParser
from mountaineer.controller import (
    ControllerBase,
    class_fn_as_method,
    get_client_functions_cls,
)
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.generics import resolve_generic_type
from mountaineer.render import RenderBase

T = TypeVar("T")


# Base data structures
@dataclass
class FieldWrapper:
    name: str
    value: Union[type["ModelWrapper"], type["EnumWrapper"], type]
    required: bool


@dataclass
class ModelWrapper:
    name: str
    model: type[BaseModel]
    isolated_model: type[BaseModel]  # Model with only direct fields
    superclasses: list["ModelWrapper"]
    value_models: list[FieldWrapper]


@dataclass
class EnumWrapper:
    name: str
    enum: type[Enum]


@dataclass
class ActionWrapper:
    name: str
    params: list[FieldWrapper]
    headers: list[FieldWrapper]
    request_body: Optional[ModelWrapper]
    response_body: Optional[ModelWrapper]
    action_type: FunctionActionType

    # Actions can be mounted to multiple controllers through inheritance
    # This will store a mapping of each controller to the url that the action is mounted to
    controller_to_url:  dict[Type[ControllerBase], str]

@dataclass
class ControllerWrapper:
    name: str
    entrypoint_url: str | None
    controller: type[ControllerBase]
    superclasses: list["ControllerWrapper"]

    # Render entrypoint
    queries: list[FieldWrapper]
    paths: list[FieldWrapper]
    render: Optional[ModelWrapper]

    # Actions
    actions: dict[
        str, ActionWrapper
    ]  # {url: action} directly implemented for this controller

    @property
    def all_actions(self) -> list[ActionWrapper]:
        # Convert each action. We also include the superclass methods, since they're
        # actually bound to the controller instance with separate urls.
        all_actions: list[ActionWrapper] = []

        # If an action is overridden in a subclass, we shouldn't include it twice
        # Unlike other traversal functions, we'd rather identify these actions
        # by their names and not memory values because we want to only show the lowest
        # subclassed implementation
        seen_actions: set[str] = set()

        def parse_controller(controller):
            for action in controller.actions.values():
                if action.name in seen_actions:
                    continue
                all_actions.append(action)
                seen_actions.add(action.name)
            for superclass in controller.superclasses:
                parse_controller(superclass)

        parse_controller(self)
        return all_actions

    @classmethod
    def get_all_embedded_types(
        cls, controllers: list["ControllerWrapper"], include_superclasses: bool = False
    ) -> tuple[list[ModelWrapper], list[EnumWrapper]]:
        """
        For all the models and enums that are embedded in this controller (actions+render), return them in a flat list.
        Results will be deduplicated.

        :param include_superclasses: If provided, we will also traverse up the hierarchy to include all models
        referenced by superclasses.

        """
        models: list[ModelWrapper] = []
        enums: list[EnumWrapper] = []

        def _traverse_logic(
            item: ControllerWrapper | ModelWrapper | EnumWrapper | TypeDefinition,
        ):
            nonlocal models, enums

            if isinstance(item, ControllerWrapper):
                if item.render:
                    yield item.render
                for action in item.all_actions:
                    if action.request_body:
                        yield action.request_body
                    if action.response_body:
                        yield action.response_body

                if include_superclasses:
                    yield from item.superclasses

            elif isinstance(item, ModelWrapper):
                models.append(item)

                for field in item.value_models:
                    yield field.value

                yield from item.superclasses

            elif isinstance(item, EnumWrapper):
                enums.append(item)

            elif isinstance(item, TypeDefinition):
                yield from item.children

        cls._traverse_iterator(_traverse_logic, controllers)
        return models, enums

    @classmethod
    def get_all_embedded_controllers(
        cls, controllers: list["ControllerWrapper"]
    ) -> list["ControllerWrapper"]:
        """
        Gets all unique superclasses of the given set of controllers.

        """
        all_controllers: list[ControllerWrapper] = []

        def _traverse_logic(item: ControllerWrapper):
            nonlocal all_controllers

            all_controllers.append(item)
            yield from item.superclasses

        cls._traverse_iterator(_traverse_logic, controllers)
        return all_controllers

    @classmethod
    def _traverse_iterator(
        cls,
        logic: Callable[[T], Generator[T, None, None]],
        initial_queue: list[T]
    ):
        """
        Memory-identity traversal, only will traverse each unique object once.
        Clients write a logic function that returns the next items to traverse, and meanwhile
        can make use of our single-traversal guarantee to store results in a flat list.

        ex:

        ```
        models = []
        def logic(item):
            if isinstance(item, ControllerWrapper):
                if item.render:
                    yield item.render
                for superclass in item.superclasses:
                    yield superclass
            elif isinstance(item, ModelWrapper):
                models.append(item)

        ```

        """
        queue = copy(initial_queue)
        already_seen: set[int] = set()
        while queue:
            item = queue.pop(0)
            if id(item) in already_seen:
                continue
            queue.extend(list(logic(item)))


@dataclass
class SelfReference:
    name: str
    model: Type[BaseModel]


class ControllerParser:
    """
    Our ControllerParser is responsible for taking the in-memory representations of
    ControllerBase models and extracting the metadata required to convert them
    through the TypeScript pipeline into full interface signatures and implementations.

    """

    def __init__(self):
        self.parsed_models: dict[type[BaseModel], ModelWrapper] = {}
        self.parsed_enums: dict[type[Enum], EnumWrapper] = {}
        self.parsed_controllers: dict[type[ControllerBase], ControllerWrapper] = {}
        self.parsed_self_references: list[SelfReference] = []

        self.type_parser = TypeParser()

    def parse_controller(self, controller: type[ControllerBase]) -> ControllerWrapper:
        """Main entry point to parse a controller into intermediary representation"""
        if controller in self.parsed_controllers:
            return self.parsed_controllers[controller]

        # Get all valid superclasses in MRO order
        base_exclude = (RenderBase, ControllerBase, LayoutControllerBase)
        controller_classes = self._get_valid_mro_classes(controller, base_exclude)

        # Get render model from the concrete controller
        render, render_path, render_query, entrypoint_url = self._parse_render(
            controller
        )
        actions = self._parse_actions(controller)

        # Parse superclasses
        superclass_controllers: list[ControllerWrapper] = []
        for superclass in controller_classes[1:]:
            superclass_controllers.append(self.parse_controller(superclass))

        wrapper = ControllerWrapper(
            name=controller.__name__,
            entrypoint_url=entrypoint_url,
            controller=controller,
            actions=actions,
            queries=render_query or [],
            paths=render_path or [],
            render=render,
            superclasses=superclass_controllers,
        )
        self.parsed_controllers[controller] = wrapper
        return wrapper

    def _parse_model(
        self, model: type[BaseModel], skip_object_ids: tuple | None = None
    ) -> ModelWrapper:
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
            # No user schema will self-reference the isolated model, it will only
            # reference the original definition
            fields.append(self._parse_field(name, field, self_model=model))

        wrapper = ModelWrapper(
            name=model.__name__,
            model=model,
            isolated_model=isolated_model,
            superclasses=superclasses,
            value_models=fields,
        )
        self.parsed_models[model] = wrapper
        return wrapper

    def _parse_field(
        self,
        name: str,
        field_info: FieldInfo,
        self_model: Type[BaseModel] | None = None,
    ) -> FieldWrapper:
        # Create a basic conversion of the types, in case they're wrapped
        # by complex types like List, Dict, etc.
        root_definition = self.type_parser.parse_type(field_info.annotation)

        # Now we can recursively parse the children
        def update_children(type_definition: TypeDefinition | type):
            if isinstance(type_definition, TypeDefinition):
                type_definition.update_children(
                    [update_children(child) for child in type_definition.children]
                )
                return type_definition
            else:
                # Special case to avoid infinite recursion
                if self_model and type_definition == self_model:
                    reference = SelfReference(
                        name=self_model.__name__, model=self_model
                    )
                    self.parsed_self_references.append(reference)
                    return reference

                # Determine if they qualify for conversion. The vast majority of values
                # passed in here will be classes, since they represent the typehinted annotations
                # of models. But there are some situations (like TypeVars used in generics) where
                # they will fail a subclass check.
                if isclass(type_definition) and issubclass(type_definition, BaseModel):
                    return self._parse_model(type_definition)
                elif isclass(type_definition) and issubclass(type_definition, Enum):
                    return self._parse_enum(type_definition)
                else:
                    # No need to parse further
                    return type_definition

        root_definition = update_children(root_definition)

        return FieldWrapper(
            name=name,
            value=root_definition,
            required=field_info.is_required(),
        )

    def _parse_enum(self, enum_type: type[Enum]) -> EnumWrapper:
        """Parse an Enum into EnumWrapper"""
        if enum_type in self.parsed_enums:
            return self.parsed_enums[enum_type]

        wrapper = EnumWrapper(name=enum_type.__name__, enum=enum_type)
        self.parsed_enums[enum_type] = wrapper
        return wrapper

    def _parse_render(
        self, controller: type[ControllerBase]
    ) -> tuple[
        ModelWrapper | None,
        list[FieldWrapper] | None,
        list[FieldWrapper] | None,
        str | None,
    ]:
        """Parse the render method's return type"""
        render = getattr(controller, "render", None)
        if not render:
            return None, None, None, None

        try:
            metadata = get_function_metadata(render)
        except AttributeError:
            return None, None, None, None

        return_model = metadata.get_render_model()
        if not return_model:
            return None, None, None, None

        # Only standard controllers will have url mounts. For layout controllers since they don't
        # mount to an actual path in the router it's fine to use any synthetic path.
        # This also applies to inherited render methods that come from a parent, they
        # can only use query params.
        entrypoint_url = metadata.controller_mounts.get(controller)

        # Only parse models and params for concrete render() implementation, not parent classes
        # that just inherit the ControllerBase's ABC generic signature
        model_schema = self._parse_model(return_model)
        path_params, query_params = self._parse_params(
            class_fn_as_method(render), "render", entrypoint_url or "/render"
        )

        return model_schema, path_params, query_params, entrypoint_url

    def _create_isolated_model(
        self,
        model: type[BaseModel],
    ) -> type[BaseModel]:
        """
        Create a new model with only the direct fields (no inherited fields).
        Handles both regular Pydantic models and generic model instances.

        """
        # For generic models, we need to synthesize annotations from the generic metadata
        if hasattr(model, "__pydantic_generic_metadata__"):
            generic_metadata = model.__pydantic_generic_metadata__
            origin = generic_metadata["origin"]
            args = generic_metadata["args"]

            # Create synthetic annotations by mapping generic parameters to concrete types
            type_params = getattr(origin, "__parameters__", ())
            type_mapping = dict(zip(type_params, args))

            # Build annotations dict by resolving generic types
            annotations = {}
            for field_name, field_info in model.model_fields.items():
                field_type = field_info.annotation
                resolved_type = resolve_generic_type(field_type, type_mapping)

                # Since we're modifying the annotation types, we need to copy the full
                # field_info since .annotation will be set on the new model. Without a copy
                # it will affect the original model's state.
                annotations[field_name] = (resolved_type, copy(field_info))

            return create_model(
                model.__name__,
                __config__=model.model_config,
                **annotations,  # type: ignore
            )
        else:
            # Regular model - use original logic
            include_fields = {
                field_name: (field_info.annotation, field_info)
                for field_name, field_info in model.model_fields.items()
                if field_name in model.__dict__.get("__annotations__", {})
            }
            return create_model(
                model.__name__,
                __config__=model.model_config,
                **include_fields,  # type: ignore
            )

    def _create_temp_route(self, func: Callable, name: str, url: str) -> APIRoute:
        """Create a temporary FastAPI route using the actual function"""
        router = APIRouter()
        router.add_api_route(
            # We need to use the right path so it can separate out the path paramss
            # from the query params
            path=f"/{url}",
            endpoint=func,
        )

        route = next(
            route
            for route in router.routes
            if isinstance(route, APIRoute) and route.path == f"/{url}"
        )

        return route

    def _parse_params(self, func: Callable, name: str, url: str):
        """Parse route parameters using FastAPI's dependency system"""
        route = self._create_temp_route(func, name, url)
        path_params: list[FieldWrapper] = [
            self._parse_field(
                name=param.name,
                field_info=param.field_info if hasattr(param, "field_info") else None,
            )
            for param in route.dependant.path_params
        ]
        query_params: list[FieldWrapper] = [
            self._parse_field(
                name=param.name,
                field_info=(param.field_info if hasattr(param, "field_info") else None),
            )
            for param in route.dependant.query_params
            if not isinstance(param.field_info, (Body, Header, Depends))
        ]

        return path_params, query_params

    def _parse_headers(self, func: Callable, name: str, url: str) -> list[FieldWrapper]:
        """Parse header parameters using FastAPI's dependency system"""
        route = self._create_temp_route(func, name, url)
        headers: list[FieldWrapper] = []

        for param in route.dependant.header_params:
            field = self._parse_field(
                name=param.name,
                field_info=param.field_info if hasattr(param, "field_info") else None,
            )
            headers.append(field)

        return headers

    def _parse_request_body(
        self, func: Callable, name: str, url: str
    ) -> Optional[ModelWrapper]:
        """Parse request body using FastAPI's dependency system"""
        route = self._create_temp_route(func, name, url)

        if route.dependant.body_params:
            body_param = route.dependant.body_params[0]  # Get first body param
            if isinstance(body_param.type_, type) and issubclass(
                body_param.type_, BaseModel
            ):
                return self._parse_model(body_param.type_)

        return None

    def _parse_response_body(
        self, metadata: FunctionMetadata
    ) -> Optional[ModelWrapper]:
        """Parse response model from metadata"""
        if not isinstance(metadata.return_model, MountaineerUnsetValue):
            model = metadata.get_return_model()
            if issubclass(model, BaseModel):
                return self._parse_model(model)
        return None

    def _parse_actions(
        self, controller: Type[ControllerBase]
    ) -> dict[str, ActionWrapper]:
        """Parse all actions in a controller"""
        actions: dict[str, ActionWrapper] = {}

        for name, func, metadata in get_client_functions_cls(controller):
            # We don't need a url for the action, since actions can't take path
            # parameters all kwargs will just be query params
            synthetic_action_url = f"/{name}"

            path_params, query_params = self._parse_params(
                func, name, synthetic_action_url
            )
            action = ActionWrapper(
                name=name,
                params=query_params,
                headers=self._parse_headers(func, name, synthetic_action_url),
                request_body=self._parse_request_body(func, name, synthetic_action_url),
                response_body=self._parse_response_body(metadata),
                action_type=metadata.action_type,
                controller_to_url=metadata.controller_mounts,
            )
            actions[name] = action

        return actions

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
