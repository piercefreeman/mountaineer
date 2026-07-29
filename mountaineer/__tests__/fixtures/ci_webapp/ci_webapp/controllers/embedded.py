from fastapi import Request
from mountaineer import ControllerBase, RenderBase, sideeffect


class EmbeddedRender(RenderBase):
    label: str
    embedded_count: int
    request_path: str


class EmbeddedController(ControllerBase):
    view_path = "/app/embedded/widget.tsx"

    def __init__(self):
        super().__init__()
        self.counts_by_label: dict[str, int] = {}

    def render(self, request: Request, label: str) -> EmbeddedRender:
        return EmbeddedRender(
            label=f"embedded:{label}",
            embedded_count=self.counts_by_label.get(label, 0),
            request_path=request.url.path,
        )

    @sideeffect(reload=(EmbeddedRender.embedded_count,))
    def increment_embedded_count(self, label: str) -> None:
        self.counts_by_label[label] = self.counts_by_label.get(label, 0) + 1
