from filzl.controller import ControllerBase
from filzl_auth import AuthDependencies, User
from filzl.dependencies import get_function_dependencies
from fastapi import Request


class DaemonControllerBase(ControllerBase):

    def __init__(self, required_admin: bool = True, user_model: User | None = None):
        super().__init__()
        self.user_model = user_model
        self.required_admin = required_admin

        if required_admin and not user_model:
            raise ValueError(
                "If required_admin is True, user_model must be provided"
            )

    async def require_admin(self, request: Request):
        if not self.required_admin:
            return

        get_dependencies_fn = AuthDependencies.require_admin(self.user_model)
        async with get_function_dependencies(
            callable=get_dependencies_fn, url=self.url, request=request
        ) as values:
            get_dependencies_fn(**values)
