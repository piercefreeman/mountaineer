from uuid import UUID

from fastapi import Request
from mountaineer import LayoutControllerBase, Metadata, RenderBase


class RootLayoutRender(RenderBase):
    layout_value: int


class RootLayoutController(LayoutControllerBase):
    view_path = "/app/layout.tsx"

    def __init__(self):
        super().__init__()
        self.layout_value = 0

    def render(self) -> RootLayoutRender:
        return RootLayoutRender(
            layout_value=self.layout_value,
        )
