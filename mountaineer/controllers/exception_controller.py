from mountaineer.controller import ControllerBase
from mountaineer.controllers.traceback import ExceptionParser, ParsedException
from mountaineer.paths import ManagedViewPath
from mountaineer.render import LinkAttribute, Metadata, RenderBase
from mountaineer.views import get_core_view_path


class ExceptionRender(RenderBase):
    exception: str
    stack: str | None

    # CSS that should be injected into the page to properly view the exceptions
    formatting_style: str
    parsed_exception: ParsedException


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.traceback_parser = ExceptionParser()

    def render(
        self, exception: str, stack: str, parsed_exception: ParsedException
    ) -> ExceptionRender:
        # Reverse the frames so they show with more specific errors at the top of the page
        parsed_exception.frames.reverse()

        # Exceptions can't be passed through as API types, so parents should pre-convert them to
        # strings before rendering
        return ExceptionRender(
            exception=exception,
            stack=stack,
            formatting_style=self.traceback_parser.get_style_defs(),
            parsed_exception=parsed_exception,
            metadata=Metadata(
                title=f"Exception: {exception}",
                links=[LinkAttribute(rel="stylesheet", href="/static/core_main.css")],
                ignore_global_metadata=True,
            ),
        )
