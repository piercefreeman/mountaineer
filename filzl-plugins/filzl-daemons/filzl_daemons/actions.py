from functools import wraps
from typing import Any, Callable

from pydantic import BaseModel


class ActionMeta(BaseModel):
    func: Callable
    args: tuple[Any] = tuple()
    kwargs: dict[str, Any] = {}


def action(f):
    @wraps(f)
    async def wrapper(*args, **kwargs):
        # return await f(*args, **kwargs)
        # we need to trap the args and kwargs
        # otherwise our run loop doesn't have access to the args once we get
        # into create_task
        return ActionMeta(
            func=f,
            args=args,
            kwargs=kwargs,
        )

    return wrapper
