from mountaineer.controller import ControllerBase
from mountaineer.render import Metadata, RenderBase


class LayoutControllerBase(ControllerBase):
    async def _generate_html(self, *args, global_metadata: Metadata | None, **kwargs):
        raise NotImplementedError

    def _generate_ssr_html(self, server_data: RenderBase) -> str:
        raise NotImplementedError
