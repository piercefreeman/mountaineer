from contextlib import AsyncExitStack, asynccontextmanager
from typing import Callable, Type, TypeVar

from fastapi import Request
from fastapi.dependencies.utils import get_dependant, solve_dependencies
from pydantic_settings import BaseSettings

from mountaineer.config import get_config

T = TypeVar("T", bound=BaseSettings)


class CoreDependencies:
    @staticmethod
    def get_config_with_type(required_type: Type[T]):
        def internal_dependency() -> T:
            config = get_config()
            if not isinstance(config, required_type):
                raise TypeError(
                    f"Expected config to inherit from {required_type}, {type(config)} is not a valid subclass"
                )
            return config

        return internal_dependency


@asynccontextmanager
async def get_function_dependencies(
    *,
    callable: Callable,
    url: str | None = None,
    request: Request | None = None,
):
    """
    Get the dependencies of a function. This will return the values that should
    be injected into the function. Provide as much metadata as possible, so we can
    resolve more accurate dependencies. If not provided, we will synthesize some values.

    """
    # Synthesize defaults
    if not url:
        url = "/synthetic"
    if not request:
        request = Request(
            scope={
                "type": "http",
                "path": url,
                "path_params": {},
                "query_string": "",
                "headers": [],
            }
        )

    # Synthetic request object as if we're coming from the original first page
    dependant = get_dependant(
        call=callable,
        path=url,
    )

    async with AsyncExitStack() as async_exit_stack:
        values, errors, background_tasks, sub_response, _ = await solve_dependencies(
            request=request,
            dependant=dependant,
            async_exit_stack=async_exit_stack,
        )
        if background_tasks:
            raise RuntimeError(
                "Background tasks are not supported when calling a static function, due to undesirable side-effects."
            )
        if errors:
            raise RuntimeError(
                f"Errors encountered while resolving dependencies: {errors}"
            )

        yield values
