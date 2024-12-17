from copy import copy
from dataclasses import dataclass
from enum import Enum
from inspect import isclass
from typing import (
    Any,
    Callable,
    Generator,
    Optional,
    Type,
    TypeVar,
    Union,
)

from fastapi import APIRouter
from fastapi.params import Body, Depends, File, Form, Header
from fastapi.routing import APIRoute
from inflection import camelize
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from mountaineer.actions.fields import (
    FunctionActionType,
    FunctionMetadata,
    get_function_metadata,
)
from mountaineer.client_builder.types import TypeDefinition, TypeParser
from mountaineer.constants import STREAM_EVENT_TYPE
from mountaineer.controller import (
    ControllerBase,
    class_fn_as_method,
    get_client_functions_cls,
)
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.exceptions import APIException as APIException
from mountaineer.render import RenderBase

T = TypeVar("T")


class WrapperName:
    # The original name given to the object, just used for record-keeping.
    raw_name: str

    # Must be globally unique.
    global_name: str

    # The name used in the local context as a shortcut while working with a single controller
    local_name: str

    def __init__(self, name: str):
        self.raw_name = name
        self.local_name = name
        self.global_name = name


@dataclass
class CoreWrapper:
    name: WrapperName
    module_name: str


@dataclass
class FieldWrapper:
    name: str
    value: Union["ModelWrapper", "EnumWrapper", "TypeDefinition", type]
    required: bool


@dataclass
class ModelWrapper(CoreWrapper):
    model: type[BaseModel]
    isolated_model: type[BaseModel]  # Model with only direct fields
    superclasses: list["ModelWrapper"]
    value_models: list[FieldWrapper]
    body_type: str = "application/json"


@dataclass
class ExceptionWrapper(CoreWrapper):
    status_code: int
    exception: Type[APIException]
    value_models: list[FieldWrapper]


@dataclass
class EnumWrapper(CoreWrapper):
    enum: type[Enum]


@dataclass
class ActionWrapper:
    name: str
    module_name: str
    action_type: FunctionActionType

    params: list[FieldWrapper]
    headers: list[FieldWrapper]
    request_body: Optional[ModelWrapper]
    response_bodies: dict[Type[ControllerBase], ModelWrapper | None]
    exceptions: list[ExceptionWrapper]

    is_raw_response: bool
    is_streaming_response: bool

    # Actions can be mounted to multiple controllers through inheritance
    # This will store a mapping of each controller to the url that the action is mounted to
    controller_to_url: dict[Type[ControllerBase], str]

    def has_required_params(self):
        return (
            (any([param.required for param in self.params]) if self.params else False)
            or (
                any([header.required for header in self.headers])
                if self.headers
                else False
            )
            or self.request_body is not None
        )


@dataclass
class ControllerWrapper(CoreWrapper):
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
    ) -> "EmbeddedTypeContainer":
        """
        For all the models and enums that are embedded in this controller (actions+render), return them in a flat list.
        Results will be deduplicated.

        :param include_superclasses: If provided, we will also traverse up the hierarchy to include all models
        referenced by superclasses.

        """
        models: list[ModelWrapper] = []
        enums: list[EnumWrapper] = []
        exceptions: list[ExceptionWrapper] = []

        def _traverse_logic(
            item: ControllerWrapper
            | ModelWrapper
            | ExceptionWrapper
            | ActionWrapper
            | EnumWrapper
            | TypeDefinition,
        ):
            nonlocal models, enums

            if isinstance(item, ControllerWrapper):
                if item.render:
                    yield item.render

                yield from item.actions.values()

                if include_superclasses:
                    yield from item.superclasses

            elif isinstance(item, ActionWrapper):
                if item.request_body:
                    yield item.request_body
                if item.response_bodies:
                    yield from item.response_bodies.values()
                yield from item.exceptions

            elif isinstance(item, ModelWrapper):
                models.append(item)

                for field in item.value_models:
                    yield field.value

                if include_superclasses:
                    yield from item.superclasses

            elif isinstance(item, EnumWrapper):
                enums.append(item)

            elif isinstance(item, ExceptionWrapper):
                exceptions.append(item)

                for field in item.value_models:
                    yield field.value

            elif isinstance(item, TypeDefinition):
                yield from item.children

        cls._traverse_iterator(_traverse_logic, controllers)
        return EmbeddedTypeContainer(models=models, enums=enums, exceptions=exceptions)

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
        logic: Callable[[T | Any], Generator[T | Any, None, None]],
        initial_queue: list[T],
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
            already_seen.add(id(item))


@dataclass
class SelfReference:
    name: str
    model: Type[BaseModel]


@dataclass
class EmbeddedTypeContainer:
    models: list[ModelWrapper]
    enums: list[EnumWrapper]
    exceptions: list[ExceptionWrapper]


class ControllerParser:
    """
    Our ControllerParser is responsible for taking the in-memory representations of
    ControllerBase models and extracting the metadata required to convert them
    through the TypeScript pipeline into full interface signatures and implementations.

    """

    def __init__(self):
        self.parsed_models: dict[Type[BaseModel], ModelWrapper] = {}
        self.parsed_enums: dict[Type[Enum], EnumWrapper] = {}
        self.parsed_controllers: dict[Type[ControllerBase], ControllerWrapper] = {}
        self.parsed_self_references: list[SelfReference] = []
        self.parsed_exceptions: dict[Type[APIException], ExceptionWrapper] = {}

        self.type_parser = TypeParser()

    def parse_controller(self, controller: type[ControllerBase]) -> ControllerWrapper:
        """Main entry point to parse a controller into intermediary representation"""
        if controller in self.parsed_controllers:
            return self.parsed_controllers[controller]

        # Get all valid superclasses in MRO order. Include any controller that is either explicitly a subclass
        # of ControllerBase or has client functions defined on it.
        controller_classes = self._get_valid_parent_classes(
            controller,
            base_require_predicate=lambda base: (
                issubclass(base, ControllerBase)
                or len(list(get_client_functions_cls(base))) > 0
            ),
            base_exclude_classes=(ControllerBase, LayoutControllerBase),
        )

        # Get render model from the concrete controller
        render, render_path, render_query, entrypoint_url = self._parse_render(
            controller
        )
        actions = self._parse_actions(controller)

        # Parse superclasses
        superclass_controllers: list[ControllerWrapper] = []
        for superclass in controller_classes:
            superclass_controllers.append(self.parse_controller(superclass))

        wrapper = ControllerWrapper(
            name=WrapperName(controller.__name__),
            module_name=controller.__module__,
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
        model_classes = self._get_valid_parent_classes(
            model, base_require=BaseModel, base_exclude_classes=(BaseModel, RenderBase)
        )

        # Parse direct superclasses (excluding the model itself)
        superclasses: list[ModelWrapper] = []
        for base in model_classes:
            if base not in self.parsed_models:
                # Now parse it properly
                self.parsed_models[base] = self._parse_model(base)
            superclasses.append(self.parsed_models[base])

        # Handle fields, excluding those from superclasses
        fields: list[FieldWrapper] = []
        isolated_model = self._create_isolated_model(model)
        for name, field in isolated_model.model_fields.items():
            if field.exclude:
                continue
            # No user schema will self-reference the isolated model, it will only
            # reference the original definition
            fields.append(self._parse_field(name, field, self_model=model))

        wrapper = ModelWrapper(
            name=WrapperName(model.__name__),
            module_name=model.__module__,
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

        # Now we can recursively parse the children. We want to wrap all of the sub-models
        # in their own wrapper objects.
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
            value=root_definition,  # type: ignore
            required=field_info.is_required(),
        )

    def _parse_enum(self, enum_type: type[Enum]) -> EnumWrapper:
        """Parse an Enum into EnumWrapper"""
        if enum_type in self.parsed_enums:
            return self.parsed_enums[enum_type]

        wrapper = EnumWrapper(
            name=WrapperName(enum_type.__name__),
            module_name=enum_type.__module__,
            enum=enum_type,
        )
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
        generic_origin: Type[BaseModel] | None = None
        generic_args: tuple[Any, ...] | None = None

        # For generic models, we need to synthesize annotations from the generic metadata
        if hasattr(model, "__pydantic_generic_metadata__"):
            generic_metadata = model.__pydantic_generic_metadata__
            generic_origin = generic_metadata["origin"]
            generic_args = generic_metadata["args"]

        if generic_origin and generic_args:
            # Build annotations dict by resolving generic types just for the fields that
            # were defined directly on the superclass. Since we're iterating with model_fields
            # on the synthetically created generic subclass, all of the annotations should be resolved
            # to real types by this point
            parent_owned_fields = generic_origin.__dict__.get("__annotations__", {})

            return create_model(  # type: ignore
                model.__name__,
                __config__=model.model_config,
                **{
                    # Since we're modifying the annotation types, we need to copy the full
                    # field_info since .annotation will be set on the new model. Without a copy
                    # it will affect the original model's state.
                    field_name: (field_info.annotation, copy(field_info))  # type: ignore
                    for field_name, field_info in model.model_fields.items()
                    if field_name in parent_owned_fields
                },
            )
        else:
            # Regular model - use original logic
            include_fields = {
                field_name: (field_info.annotation, field_info)
                for field_name, field_info in model.model_fields.items()
                if field_name in model.__dict__.get("__annotations__", {})
            }
            return create_model(  # type: ignore
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
            # We don't use the FastAPI's sniffed response model parsing in our pipeline, and
            # some definitions like server-side streaming AsyncIterables can't be handled
            # natively by FastAPI
            response_model=None,
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
                field_info=param.field_info,
            )
            for param in route.dependant.path_params
        ]
        query_params: list[FieldWrapper] = [
            self._parse_field(
                name=param.name,
                field_info=param.field_info,
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
                field_info=param.field_info,
            )
            headers.append(field)

        return headers

    def _parse_request_body(
        self, func: Callable, name: str, url: str
    ) -> Optional[ModelWrapper]:
        """Parse request body using FastAPI's dependency system"""
        route = self._create_temp_route(func, name, url)

        if not route.dependant.body_params:
            return None

        body_fields: dict[str, FieldInfo] = {}
        has_files = False
        has_form = False

        # Analyze all body parameters
        for body_param in route.dependant.body_params:
            field_info = body_param.field_info
            field_type = body_param.type_

            # Handle Pydantic models
            if isinstance(field_type, type) and issubclass(field_type, BaseModel):
                return self._parse_model(field_type)

            # Handle File uploads, subclass of Form
            elif isinstance(field_info, File):
                has_files = True
                body_fields[body_param.name] = field_info

            # Handle Form fields
            elif isinstance(field_info, Form):
                has_form = True
                body_fields[body_param.name] = field_info

        # Create dynamic model for the body, since forms don't otherwise
        # have a Pydantic model that wraps the values
        body_model = create_model(
            f"{camelize(name)}Form",
            __module__=func.__module__,
            **{
                name: (field_info.annotation, field_info)  # type: ignore
                for name, field_info in body_fields.items()
            },
        )

        # Determine the type of request body
        if has_files:
            body_type = "multipart/form-data"
        elif has_form:
            body_type = "application/x-www-form-urlencoded"
        else:
            return None

        model_wrapped = self._parse_model(body_model)
        model_wrapped.body_type = body_type
        return model_wrapped

    def _parse_response_bodies(self, metadata: FunctionMetadata):
        """Parse response model from metadata"""
        return {
            controller: self._parse_model(model)
            if issubclass(model, BaseModel)
            else None
            for controller, model in metadata.return_models.items()
        }

    def _parse_actions(self, controller: type) -> dict[str, ActionWrapper]:
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
                module_name=controller.__module__,
                params=query_params,
                headers=self._parse_headers(func, name, synthetic_action_url),
                request_body=self._parse_request_body(func, name, synthetic_action_url),
                response_bodies=self._parse_response_bodies(metadata),
                is_raw_response=metadata.is_raw_response,
                is_streaming_response=metadata.media_type == STREAM_EVENT_TYPE,
                exceptions=[
                    self._parse_exception(exception)
                    for exception in metadata.exception_models
                ],
                action_type=metadata.action_type,
                controller_to_url=metadata.controller_mounts,
            )
            actions[name] = action

        return actions

    def _parse_exception(self, exception: Type[APIException]):
        if exception in self.parsed_exceptions:
            return self.parsed_exceptions[exception]

        value_models = [
            self._parse_field(name, field_info)
            for name, field_info in exception.InternalModel.model_fields.items()
        ]

        # Unlike standard Models, which are used 1:1 to validate client bodies where some
        # fields are required and others can safely be left missing to default to a
        # server-side value, we know exceptions will be fully populated at runtime. The
        # non-required fields within InternalModel only indicate at exception instance
        # creation what clients have to supply for every constructor versus what
        # is inherited from the superclass.
        for field in value_models:
            field.required = True

        wrapper = ExceptionWrapper(
            name=WrapperName(exception.__name__),
            module_name=exception.__module__,
            status_code=exception.status_code,
            exception=exception,
            value_models=value_models,
        )
        self.parsed_exceptions[exception] = wrapper
        return wrapper

    def _get_valid_parent_classes(
        self,
        cls: type,
        *,
        base_require: type | None = None,
        base_require_predicate: Callable[[type], bool] | None = None,
        base_exclude_classes: tuple[type, ...],
    ) -> list[type]:
        """
        Helper to get valid MRO parents, excluding certain base classes

        """
        return [
            base
            for base in cls.__bases__
            if (
                base not in base_exclude_classes
                and base is not object
                and (not base_require or issubclass(base, base_require))
                and (not base_require_predicate or base_require_predicate(base))
            )
        ]
