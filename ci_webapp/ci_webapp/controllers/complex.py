from uuid import UUID, uuid4

from fastapi import Request
from mountaineer import ControllerBase, Metadata, RenderBase


class ComplexRender(RenderBase):
    client_ip: str
    random_uuid: UUID
    delay_loops: int
    throw_client_error: bool


class ComplexController(ControllerBase):
    """
    We set up our Complex controller and view to simulate what a long running
    React render looks on the client side. Because of our naive prime-number loop,
    each "delay_loop" is expected to saturate the process with work for about 2s.

    Adusting the `delay_loops` parameter on the view will allow you to set
    the number of loops and therefore the total rendering time that it takes.
    This in-turn lets you test our timeout of 10s for a rendering job.

    """

    url = "/complex/{detail_id}/"
    view_path = "/app/complex/page.tsx"

    def __init__(self):
        super().__init__(
            hard_ssr_timeout=5,
        )

    def render(
        self,
        detail_id: UUID,
        request: Request,
        delay_loops: int | None = None,
        throw_client_error: bool = False,
    ) -> ComplexRender:
        return ComplexRender(
            client_ip=request.client.host if request.client else "unknown",
            random_uuid=uuid4(),
            metadata=Metadata(title=f"Complex: {detail_id}"),
            delay_loops=delay_loops or 0,
            throw_client_error=throw_client_error,
        )
