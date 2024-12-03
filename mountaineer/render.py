from hashlib import sha256
from json import dumps as json_dumps
from typing import TYPE_CHECKING, Any, Mapping, Type, TypeVar
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from fastapi import Response
from pydantic import BaseModel, model_validator
from pydantic._internal._model_construction import ModelMetaclass
from pydantic.fields import Field, FieldInfo
from typing_extensions import dataclass_transform

from mountaineer.client_compiler.build_metadata import BuildMetadata

T = TypeVar("T")


class FieldClassDefinition(BaseModel):
    root_model: Type[BaseModel]
    key: str
    field_definition: FieldInfo

    model_config = {
        "arbitrary_types_allowed": True,
    }


@dataclass_transform(kw_only_default=True, field_specifiers=(Field,))
class ReturnModelMetaclass(ModelMetaclass):
    INTERNAL_RENDER_FIELDS = ["metadata"]

    if not TYPE_CHECKING:  # pragma: no branch
        # Following the lead of the pydantic superclass, we wrap with a non-TYPE_CHECKING
        # block: "otherwise mypy allows arbitrary attribute access""

        def __new__(
            self,
            cls_name: str,
            bases: tuple[type[Any], ...],
            namespace: dict[str, Any],
            *args,
            **kwargs: Any,
        ):
            # Pydantic uses exceptions in the __getattr__ to handle collection of fields
            # in set_model_fields. While we're still initializing the class we have no
            # need for our custom accessor logic - so we temporarily turn it off.
            self.is_constructing = True
            obj = super().__new__(self, cls_name, bases, namespace, *args, **kwargs)
            self.is_constructing = False
            return obj

        def __getattr__(self, key: str) -> Any:
            if self.is_constructing:
                return super().__getattr__(key)

            try:
                return super().__getattr__(key)
            except AttributeError:
                # Determine if this field is defined within the spec
                # If so, return it
                if key in self.model_fields and key not in self.INTERNAL_RENDER_FIELDS:
                    return FieldClassDefinition(
                        root_model=self,
                        key=key,
                        field_definition=self.model_fields[key],
                    )
                raise


class HashableAttribute(BaseModel):
    """
    Even with frozen=True, we can't hash our attributes because they include dictionary field types.
    Instead provide a mixin to calculate the hash of the current state of the attributes.

    """

    def __hash__(self):
        model_json = json_dumps(self.model_dump(), sort_keys=True)
        hash_object = sha256(model_json.encode())
        # __hash__ must return an integer
        return int(hash_object.hexdigest(), 16)


class MetaAttribute(HashableAttribute, BaseModel):
    """
    Represents a meta tag that can be included in the head of an HTML document.

    ```python {{ sticky: True }}
    MetaAttribute(
        name="description",
        content="This is a description of the page.",
        optional_attributes={"lang": "en"},
    )
    ```

    """

    name: str | None = None
    content: str | None = None
    optional_attributes: dict[str, str] = {}


class ThemeColorMeta(MetaAttribute):
    """
    Customizes the default color that is attached to the page.

    ```python {{ sticky: True }}
    ThemeColorMeta(
        color="white",
        media="light",
    )
    ```

    """

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
    """
    Defines the bounds on the current page and how much users are able to zoom.

    ```python {{ sticky: True }}
    ViewportMeta(
        initial_scale=1.0,
        maximum_scale=2.0,
        user_scalable=True,
    )
    ```

    """

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


class LinkAttribute(HashableAttribute, BaseModel):
    """
    Inject a generic <link> tag into the <head> of the current page.

    ```python {{ sticky: True }}
    LinkAttribute(
        rel="stylesheet",
        href="https://example.com/styles.css",
        optional_attributes={"media": "screen"},
    )
    ```

    """

    rel: str
    href: str
    optional_attributes: dict[str, str] = {}

    # A sha will only be added automatically for link imports
    # that reference files built into the _static directory at runtime. Other
    # links will remain as-is without a resolved sha.
    add_static_sha: bool = True

    def set_sha(self, sha: str):
        """
        Updates the URL by adding or modifying the 'sha' query parameter. If a sha
        is already provided as part of href, will override the existing sha.

        """
        # Existing URL components
        parsed_url = urlparse(self.href)
        query_params = parse_qs(parsed_url.query)

        query_params["sha"] = [sha]
        new_query = urlencode(query_params, doseq=True)

        self.href = urlunparse(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                parsed_url.params,
                new_query,
                parsed_url.fragment,
            )
        )


class ScriptAttribute(HashableAttribute, BaseModel):
    """
    Inject a generic <script> tag into the <head> of the current page.

    ```python {{ sticky: True }}
    ScriptAttribute(
        src="https://example.com/script.js",
        asynchronous=True,
        optional_attributes={"defer": "true"},
        defer=False,
    )
    ```

    """

    src: str
    asynchronous: bool = False
    defer: bool = False
    optional_attributes: dict[str, str] = {}


class Metadata(BaseModel):
    """
    Metadata lets the client specify the different metadata definitions that should
    appear on the current page. These are outside the scope of React management so are
    only handled once on the initial page render. But because they still receive the initial
    render request, you can add any dynamic logic that you want to customize the behavior
    of the page metadata. This includes templating the page title depending on a remote value,
    modifying the scripts injected depending on the user, etc.

    ```python {{ sticky: True }}
    class MyController(Controller):
        async def render(
            self,
            user_name: str,
        ):
            return MyControllerRender(
                metadata=Metadata(
                    title=f"Welcome, {user_name}!",
                )
            )
    ```

    ```python {{ sticky: True }}
    Metadata(
        title="My Page",
        metas=[
            MetaAttribute(...),
            ThemeColorMeta(...),
            ViewportMeta(...),
        ],
        links=[
            LinkAttribute(...),
        ]
    )
    ```

    """

    title: str | None = None

    # Specify dynamic injection of tags into the <head>
    metas: list[MetaAttribute] = []
    links: list[LinkAttribute] = []
    scripts: list[ScriptAttribute] = []

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

    def merge(self, parent: "Metadata") -> "Metadata":
        def merge_item(a: list[T], b: list[T]):
            # Keeps the original ordering while avoiding duplicates
            for item in b:
                if item not in a:
                    a.append(item)
            return a

        return Metadata(
            title=self.title or parent.title,
            metas=merge_item(self.metas, parent.metas),
            links=merge_item(self.links, parent.links),
            scripts=merge_item(self.scripts, parent.scripts),
            explicit_response=self.explicit_response,
            ignore_global_metadata=self.ignore_global_metadata,
        )

    def build_header(self, build_metadata: BuildMetadata | None) -> list[str]:
        """
        Builds the header for this controller. Returns the list of tags that will be injected into the
        <head> tag of the rendered page.

        """
        tags: list[str] = []

        def format_optional_keys(payload: Mapping[str, str | bool | None]) -> str:
            attributes: list[str] = []
            for key, value in payload.items():
                if value is None:
                    continue
                elif isinstance(value, bool):
                    # Boolean attributes can just be represented by just their key
                    if value:
                        attributes.append(key)
                    else:
                        continue
                else:
                    attributes.append(f'{key}="{value}"')
            return " ".join(attributes)

        if self.title:
            tags.append(f"<title>{self.title}</title>")

        for meta_definition in self.metas:
            meta_attributes = {
                "name": meta_definition.name,
                "content": meta_definition.content,
                **meta_definition.optional_attributes,
            }
            tags.append(f"<meta {format_optional_keys(meta_attributes)} />")

        for script_definition in self.scripts:
            script_attributes: dict[str, str | bool] = {
                "src": script_definition.src,
                "async": script_definition.asynchronous,
                "defer": script_definition.defer,
                **script_definition.optional_attributes,
            }
            tags.append(f"<script {format_optional_keys(script_attributes)}></script>")

        for link_definition in self.links:
            if build_metadata and link_definition.add_static_sha:
                # By convention, static files should be mounted to the application in a /static endpoint. These
                # may be served outside of mountaineer (via a CDN or similar) but we still expect
                # these paths to reference the proper paths
                link_sha: str | None = None
                for (
                    static_path,
                    static_sha,
                ) in build_metadata.static_artifact_shas.items():
                    # Allow for alternative endings to support existing query parameters
                    if link_definition.href.startswith(f"/static/{static_path}"):
                        link_sha = static_sha
                if link_sha:
                    link_definition.set_sha(link_sha)

            link_attributes = {
                "rel": link_definition.rel,
                "href": link_definition.href,
                **link_definition.optional_attributes,
            }

            tags.append(f"<link {format_optional_keys(link_attributes)} />")

        return tags


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
