from dataclasses import dataclass
from datetime import date, datetime, time
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import UploadFile
from inflection import camelize
from pydantic import BaseModel, Field

from mountaineer.client_builder.parser import (
    ActionWrapper,
    ControllerParser,
    ControllerWrapper,
    EnumWrapper,
    ExceptionWrapper,
    FieldWrapper,
    ModelWrapper,
    SelfReference,
)
from mountaineer.client_builder.types import (
    DictOf,
    ListOf,
    LiteralOf,
    Or,
    SetOf,
    TupleOf,
)
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath

JsonPrimitive = str | int | float | bool | None


class SchemaManifest(BaseModel):
    """OpenAPI-compatible schema used by the native client compiler."""

    ref: str | None = Field(default=None, serialization_alias="$ref")
    type: str | None = None
    format: str | None = None
    any_of: tuple["SchemaManifest", ...] = Field(
        default=(), serialization_alias="anyOf"
    )
    all_of: tuple["SchemaManifest", ...] = Field(
        default=(), serialization_alias="allOf"
    )
    items: "SchemaManifest | None" = None
    prefix_items: tuple["SchemaManifest", ...] = Field(
        default=(), serialization_alias="prefixItems"
    )
    enum: tuple[JsonPrimitive, ...] = ()
    properties: dict[str, "SchemaManifest"] = {}
    required: tuple[str, ...] = ()
    additional_properties: "SchemaManifest | None" = Field(
        default=None, serialization_alias="additionalProperties"
    )
    unique_items: bool = Field(default=False, serialization_alias="uniqueItems")
    mountaineer_key: "SchemaManifest | None" = Field(
        default=None, serialization_alias="x-mountaineer-key"
    )


class FieldManifest(BaseModel):
    """Named controller or model field."""

    name: str
    value: SchemaManifest = Field(serialization_alias="schema")
    required: bool


class EnumMemberManifest(BaseModel):
    """Named member of a Python enum."""

    name: str
    value: JsonPrimitive


class ComponentManifest(BaseModel):
    """Named schema component exposed to generated clients."""

    kind: Literal["model", "enum", "exception"]
    global_name: str
    local_name: str
    value: SchemaManifest = Field(serialization_alias="schema")
    status_code: int | None = None
    enum_members: tuple[EnumMemberManifest, ...] = ()


class ActionManifest(BaseModel):
    """Controller action and its concrete mount metadata."""

    name: str
    action_type: Literal["sideeffect", "passthrough", "render"]
    params: tuple[FieldManifest, ...]
    headers: tuple[FieldManifest, ...]
    request_body: str | None
    request_media_type: str | None
    responses: dict[str, str | None]
    exceptions: tuple[str, ...]
    urls: dict[str, str]
    is_raw_response: bool
    is_streaming_response: bool


class ControllerManifest(BaseModel):
    """Controller type exposed to generated clients."""

    global_name: str
    local_name: str
    parents: tuple[str, ...]
    actions: tuple[ActionManifest, ...]


class ViewManifest(BaseModel):
    """Concrete mounted view and the client files it owns."""

    controller: str
    server_key: str
    link_name: str
    managed_dir: str
    entrypoint_url: str | None
    is_layout: bool
    render: str | None
    queries: tuple[FieldManifest, ...]
    paths: tuple[FieldManifest, ...]
    actions: tuple[ActionManifest, ...]
    controllers: tuple[str, ...]
    components: tuple[str, ...]


class MountaineerEnvelope(BaseModel):
    """Versioned boundary between Python introspection and native generation."""

    schema_version: Literal[1]
    mountaineer_version: str
    global_root: str
    components: tuple[ComponentManifest, ...]
    controllers: tuple[ControllerManifest, ...]
    views: tuple[ViewManifest, ...]


@dataclass
class ParsedView:
    """Parsed controller paired with its filesystem mount."""

    wrapper: ControllerWrapper
    view_path: ManagedViewPath
    is_layout: bool = False


def build_envelope(
    parser: ControllerParser,
    views: list[ParsedView],
    global_root: Path,
) -> MountaineerEnvelope:
    """Serialize parsed controllers into the native compiler boundary."""

    return MountaineerEnvelope(
        schema_version=1,
        mountaineer_version=version("mountaineer"),
        global_root=str(global_root.resolve()),
        components=tuple(
            _component(component)
            for component in (
                *parser.parsed_models.values(),
                *parser.parsed_enums.values(),
                *parser.parsed_exceptions.values(),
            )
        ),
        controllers=tuple(
            _controller(controller, parser)
            for controller in parser.parsed_controllers.values()
        ),
        views=tuple(_view(view, parser) for view in views),
    )


def _schema(value: Any) -> SchemaManifest:
    if isinstance(value, (ModelWrapper, EnumWrapper, ExceptionWrapper)):
        return _ref(value.name.global_name)
    if isinstance(value, SelfReference):
        return _ref(value.name)
    if isinstance(value, Or):
        return SchemaManifest(any_of=tuple(_schema(item) for item in value.types))
    if isinstance(value, ListOf):
        return SchemaManifest(type="array", items=_schema(value.type))
    if isinstance(value, TupleOf):
        return SchemaManifest(
            type="array", prefix_items=tuple(_schema(item) for item in value.types)
        )
    if isinstance(value, SetOf):
        return SchemaManifest(
            type="array", items=_schema(value.type), unique_items=True
        )
    if isinstance(value, DictOf):
        return SchemaManifest(
            type="object",
            additional_properties=_schema(value.value_type),
            mountaineer_key=_schema(value.key_type),
        )
    if isinstance(value, LiteralOf):
        return SchemaManifest(enum=tuple(value.values))

    primitive = _primitive(value)
    if primitive is not None:
        return primitive

    LOGGER.warning("Unknown client type %r; using any", value)
    return SchemaManifest()


def _primitive(value: Any) -> SchemaManifest | None:
    roots: tuple[tuple[type, SchemaManifest], ...] = (
        (str, SchemaManifest(type="string")),
        (bool, SchemaManifest(type="boolean")),
        (int, SchemaManifest(type="number")),
        (float, SchemaManifest(type="number")),
        (datetime, SchemaManifest(type="string", format="date-time")),
        (date, SchemaManifest(type="string", format="date")),
        (time, SchemaManifest(type="string", format="time")),
        (UUID, SchemaManifest(type="string", format="uuid")),
        (UploadFile, SchemaManifest(type="string", format="binary")),
        (type(None), SchemaManifest(type="null")),
    )
    if value is Any:
        return SchemaManifest()
    if not isinstance(value, type):
        return None
    for root, schema in roots:
        if issubclass(value, root):
            return schema
    return None


def _ref(name: str) -> SchemaManifest:
    return SchemaManifest(ref=f"#/components/schemas/{name}")


def _fields(fields: list[FieldWrapper]) -> tuple[FieldManifest, ...]:
    return tuple(
        FieldManifest(
            name=field.name, value=_schema(field.value), required=field.required
        )
        for field in fields
    )


def _object_schema(
    fields: list[FieldWrapper], parents: list[ModelWrapper] | None = None
) -> SchemaManifest:
    return SchemaManifest(
        type="object",
        properties={field.name: _schema(field.value) for field in fields},
        required=tuple(field.name for field in fields if field.required),
        all_of=tuple(_ref(parent.name.global_name) for parent in parents or []),
    )


def _component(
    wrapper: ModelWrapper | EnumWrapper | ExceptionWrapper,
) -> ComponentManifest:
    if isinstance(wrapper, ModelWrapper):
        return ComponentManifest(
            kind="model",
            global_name=wrapper.name.global_name,
            local_name=wrapper.name.local_name,
            value=_object_schema(wrapper.value_models, wrapper.superclasses),
        )
    if isinstance(wrapper, ExceptionWrapper):
        return ComponentManifest(
            kind="exception",
            global_name=wrapper.name.global_name,
            local_name=wrapper.name.local_name,
            status_code=wrapper.status_code,
            value=_object_schema(wrapper.value_models),
        )
    return ComponentManifest(
        kind="enum",
        global_name=wrapper.name.global_name,
        local_name=wrapper.name.local_name,
        value=SchemaManifest(
            enum=tuple(member.value for member in wrapper.enum.__members__.values())
        ),
        enum_members=tuple(
            EnumMemberManifest(name=name, value=member.value)
            for name, member in wrapper.enum.__members__.items()
        ),
    )


def _action(action: ActionWrapper, parser: ControllerParser) -> ActionManifest:
    responses = {
        parser.parsed_controllers[controller].name.global_name: (
            body.name.global_name if body else None
        )
        for controller, body in action.response_bodies.items()
        if controller in parser.parsed_controllers
    }
    urls = {
        parser.parsed_controllers[controller].name.global_name: url
        for controller, url in action.controller_to_url.items()
        if controller in parser.parsed_controllers
    }
    return ActionManifest(
        name=action.name,
        action_type=action.action_type.value,
        params=_fields(action.params),
        headers=_fields(action.headers),
        request_body=(
            action.request_body.name.global_name if action.request_body else None
        ),
        request_media_type=action.request_body.body_type
        if action.request_body
        else None,
        responses=responses,
        exceptions=tuple(exception.name.global_name for exception in action.exceptions),
        urls=urls,
        is_raw_response=action.is_raw_response,
        is_streaming_response=action.is_streaming_response,
    )


def _controller(
    controller: ControllerWrapper, parser: ControllerParser
) -> ControllerManifest:
    return ControllerManifest(
        global_name=controller.name.global_name,
        local_name=controller.name.local_name,
        parents=tuple(parent.name.global_name for parent in controller.superclasses),
        actions=tuple(
            _action(action, parser) for action in controller.actions.values()
        ),
    )


def _view(view: ParsedView, parser: ControllerParser) -> ViewManifest:
    wrapper = view.wrapper
    embedded = ControllerWrapper.get_all_embedded_types(
        [wrapper], include_superclasses=True
    )
    return ViewManifest(
        controller=wrapper.name.global_name,
        server_key=wrapper.controller.__name__,
        link_name=camelize(wrapper.controller.__name__, uppercase_first_letter=False),
        managed_dir=str(view.view_path.get_managed_code_dir().resolve()),
        entrypoint_url=wrapper.entrypoint_url,
        is_layout=view.is_layout,
        render=wrapper.render.name.global_name if wrapper.render else None,
        queries=_fields(wrapper.queries),
        paths=_fields(wrapper.paths),
        actions=tuple(_action(action, parser) for action in wrapper.all_actions),
        controllers=tuple(
            controller.name.global_name
            for controller in ControllerWrapper.get_all_embedded_controllers([wrapper])
        ),
        components=tuple(
            item.name.global_name for item in (*embedded.models, *embedded.enums)
        ),
    )
