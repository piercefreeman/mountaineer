from mountaineer import LayoutControllerBase, RenderBase
from mountaineer.actions import sideeffect


class RootLayoutRender(RenderBase):
    layout_value: int
    layout_arg: int


class RootLayoutController(LayoutControllerBase):
    view_path = "/app/layout.tsx"

    def __init__(self):
        super().__init__()
        self.layout_value = 0

    def render(self, layout_arg: int | None = None) -> RootLayoutRender:
        return RootLayoutRender(
            layout_value=self.layout_value,
            layout_arg=layout_arg or 0,
        )

    @sideeffect
    async def increment_layout_value(self) -> None:
        self.layout_value += 1
