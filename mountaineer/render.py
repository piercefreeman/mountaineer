from typing import TYPE_CHECKING, Any, Type

from fastapi import Response
from pydantic import BaseModel, model_validator
from pydantic._internal._model_construction import ModelMetaclass
from pydantic.fields import Field, FieldInfo
from typing_extensions import dataclass_transform


class FieldClassDefinition(BaseModel):
    root_model: Type[BaseModel]
    key: str
    field_definition: FieldInfo

    model_config = {
        "arbitrary_types_allowed": True,
    }


INTERNAL_RENDER_FIELDS = ["metadata"]


@dataclass_transform(kw_only_default=True, field_specifiers=(Field,))
class ReturnModelMetaclass(ModelMetaclass):
    if not TYPE_CHECKING:  # pragma: no branch
        # Following the lead of the pydantic superclass, we wrap with a non-TYPE_CHECKING
        # block: "otherwise mypy allows arbitrary attribute access""
        def __getattr__(self, key: str) -> Any:
            try:
                return super().__getattr__(key)
            except AttributeError:
                # Determine if this field is defined within the spec
                # If so, return it
                if key in self.model_fields and key not in INTERNAL_RENDER_FIELDS:
                    return FieldClassDefinition(
                        root_model=self,
                        key=key,
                        field_definition=self.model_fields[key],
                    )
                raise


class MetaAttribute(BaseModel):
    name: str | None = None
    content: str | None = None
    optional_attributes: dict[str, str] = {}


class ThemeColorMeta(MetaAttribute):
    color: str
    media: str | None = None

    @model_validator(mode="after")
    def create_attribute(self):
        self.name = "theme-color"
        self.content = self.color
        if self.media:
            self.optional_attributes = {"media": self.media}
        return self


class ViewportMeta(MetaAttribute):
    width: str = "device-width"
    initial_scale: float = 1.0
    maximum_scale: float = 1.0
    user_scalable: bool = False

    @model_validator(mode="after")
    def create_attribute(self):
        user_scalable_str = "yes" if self.user_scalable else "no"

        self.name = "viewport"
        self.content = f"width={self.width}, initial-scale={self.initial_scale}, maximum-scale={self.maximum_scale}, user-scalable={user_scalable_str}"
        return self


class LinkAttribute(BaseModel):
    rel: str
    href: str
    optional_attributes: dict[str, str] = {}


class Metadata(BaseModel):
    """
    Metadata lets the client specify the different metadata definitions that should
    appear on the current page. These are outside the scope of React management so are
    only handled once on the initial page render.

    """

    title: str | None = None

    metas: list[MetaAttribute] = []
    links: list[LinkAttribute] = []

    # Allows the client to specify a different response type
    # that should occur on initial render
    # Useful for redirects, adding cookies, etc.
    explicit_response: Response | None = None

    # If enabled, we won't attempt to use the global metadata for this route
    # Helpful for plugins or otherwise for nested routes that should escape the container
    ignore_global_metadata: bool = False

    model_config = {
        "extra": "forbid",
        "arbitrary_types_allowed": True,
    }


class RenderBase(BaseModel, metaclass=ReturnModelMetaclass):
    """
    Base class for all renderable data models. Subclass this model when defining
    your own component data schema.
    """

    metadata: Metadata | None = Field(default=None, exclude=True)

    model_config = {
        # Frozen parameters are required so we can hash the render values to check
        # for changes in our SSR renderer
        "frozen": True,
    }


class RenderNull(RenderBase):
    pass
