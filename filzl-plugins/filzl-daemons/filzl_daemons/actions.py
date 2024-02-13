from functools import wraps
from inspect import iscoroutinefunction, signature

from pydantic import BaseModel

from filzl_daemons.logging import LOGGER
from filzl_daemons.registry import REGISTRY


class ActionExecutionStub(BaseModel):
    registry_id: str
    input_body: BaseModel | None = None


def action(f):
    global REGISTRY

    # Require the function to be async
    if not iscoroutinefunction(f):
        raise Exception(
            f"Function {f.__name__} is not a coroutine function. Use async def instead of def."
        )

    # Require the function to either have:
    # - No arguments
    # - A pydantic model as the first argument
    sig = signature(f)
    params = list(sig.parameters.values())
    if len(params) > 1:
        raise TypeError(
            f"Function {f.__name__} must have no arguments or the first argument must be a Pydantic model."
        )

    first_argument = params[0] if len(params) > 0 else None
    action_model = first_argument.annotation if first_argument is not None else None

    if action_model is not None and not issubclass(action_model, BaseModel):
        raise TypeError(
            f"The first argument of {f.__name__} must be a Pydantic model or there should be no arguments."
        )

    LOGGER.debug(f"Adding to registry: {f.__name__} ({action_model})")
    registry_id = REGISTRY.register_action(f, action_model)

    @wraps(f)
    async def wrapper(input_body: BaseModel | None = None, *args, **kwargs):
        # We need to trap the input_model submitted to the task
        # Otherwise our run loop doesn't have access to the args once we get
        # into create_task, so they can't be delegated to other processes
        # We don't expect to actually have any args/kwargs here, but we ignore them
        # if they're provided
        print("Try to create ActionExecutionStub", registry_id, input_body)
        return ActionExecutionStub(
            registry_id=registry_id,
            input_body=input_body,
        )

    return wrapper
