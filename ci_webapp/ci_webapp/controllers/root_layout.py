from mountaineer import LayoutControllerBase, RenderBase
from mountaineer.actions import sideeffect


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

    @sideeffect
    async def increment_layout_value(self) -> None:
        self.layout_value += 1
