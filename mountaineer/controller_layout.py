from mountaineer.controller import ControllerBase


class LayoutControllerBase(ControllerBase):
    async def _generate_html(self, *args, global_metadata, **kwargs):
        raise NotImplementedError

    def _generate_ssr_html(self, server_data) -> str:
        raise NotImplementedError
