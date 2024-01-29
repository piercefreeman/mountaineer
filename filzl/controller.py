from abc import ABC, abstractmethod
from inspect import getmembers, ismethod
from pathlib import Path
from typing import Callable, Iterable

from fastapi.responses import HTMLResponse

from filzl.actions import (
    FunctionActionType,
    FunctionMetadata,
    get_function_metadata,
)
from filzl.render import RenderBase


class ControllerBase(ABC):
    url: str
    view_path: str | Path

    @abstractmethod
    def render(self, *args, **kwargs) -> RenderBase:
        pass

    def _generate_html(self, *args, **kwargs):
        # TODO: Implement SSR
        _ = self.render(*args, **kwargs)

        TEMPLATE = """
        <html>
        <head>
        <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
        <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
        </head>
        <body>
        <div id="root"></div>
        <script type="text/javascript">
        // es-build output for a simple built application
        // app/layout.tsx
        var Layout = ({ children }) => {
          return /* @__PURE__ */ React.createElement("div", null, "Layout1 ", children);
        };
        var layout_default = Layout;

        // app/whee2/layout.tsx
        var Layout2 = ({ children }) => {
          return /* @__PURE__ */ React.createElement("div", null, "Layout2 ", children);
        };
        var layout_default2 = Layout2;

        // app/whee2/page.tsx
        var Page = () => {
          return /* @__PURE__ */ React.createElement("div", null, "Page 2");
        };
        var page_default = Page;

        // synthetic/page.tsx
        var Entrypoint = () => {
          return /* @__PURE__ */ React.createElement(layout_default, null, /* @__PURE__ */ React.createElement(layout_default2, null, /* @__PURE__ */ React.createElement(page_default, null)));
        };
        ReactDOM.render(/* @__PURE__ */ React.createElement(Entrypoint, null), document.getElementById("root"));
        </script>
        </body>
        </html>
        """

        # return HTMLResponse(Path(self.view_path).read_text())
        return HTMLResponse(TEMPLATE)

    def _get_client_functions(self) -> Iterable[tuple[str, Callable, FunctionMetadata]]:
        """
        Returns all of the client-callable functions for this controller. Right now we force
        client accessible functions to either be wrapped by @sideeffect or @passthrough.

        """
        # Iterate over all the functions in this class and see which ones have a _metadata attribute
        for name, func in getmembers(self, predicate=ismethod):
            try:
                metadata = get_function_metadata(func)
                if metadata.action_type in {
                    FunctionActionType.PASSTHROUGH,
                    FunctionActionType.SIDEEFFECT,
                }:
                    yield name, func, metadata
            except AttributeError:
                continue
