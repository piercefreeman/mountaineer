from mountaineer.controller import ControllerBase


class LayoutControllerBase(ControllerBase):
    """
    Base class for layouts. Layout controllers are used to generate the HTML that wrap
    a regular view controller. They support all actions that a regular controller
    does (@sideeffect and @passthrough).

    Their limitations:
    - They are run in an isolated dependency injection context, they don't share
        dependency injected values with the given page
    - The current page Request is not supported within render()
    - Sideeffect updates to the layout don't affect the page state, and vice-versa
    - Layout controllers can't be mounted as a URL route

    """

    async def _generate_html(self, *args, global_metadata, **kwargs):
        raise NotImplementedError

    def _generate_ssr_html(self, server_data) -> str:
        raise NotImplementedError
