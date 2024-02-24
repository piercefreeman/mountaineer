from mountaineer.controller import ControllerBase
from mountaineer.paths import ManagedViewPath
from mountaineer.render import LinkAttribute, Metadata, RenderBase
from mountaineer.views import get_core_view_path


class ExceptionRender(RenderBase):
    exception: str
    stack: str | None


class ExceptionController(ControllerBase):
    """
    Controller intended for internal use only. Allows our development server
    to render exceptions in the browser and leverage our SSR-injected live reloading.

    """

    url = "/_exception"
    view_path = (
        ManagedViewPath.from_view_root(get_core_view_path(""), package_root_link=None)
        / "core/exception/page.tsx"
    )

    def render(self, exception: str, stack: str) -> ExceptionRender:
        # Exceptions can't be passed through as API types, so parents should pre-convert them to
        # strings before rendering
        return ExceptionRender(
            exception=exception,
            stack=stack,
            metadata=Metadata(
                title=f"Exception: {exception}",
                links=[LinkAttribute(rel="stylesheet", href="/static/core_main.css")],
                ignore_global_metadata=True,
            ),
        )
