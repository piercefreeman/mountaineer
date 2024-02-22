from functools import wraps
from inspect import isclass, iscoroutinefunction, signature

from fastapi.params import Depends
from filzl.dependencies import get_function_dependencies
from pydantic import BaseModel

from filzl_daemons.registry import REGISTRY


class ActionExecutionStub(BaseModel):
    registry_id: str
    input_body: BaseModel | None = None


def action(f):
    # Require the function to be async
    if not iscoroutinefunction(f):
        raise ValueError(
            f"Function {f.__name__} is not a coroutine function. Use async def instead of def."
        )

    # Require the function to either have:
    # - No arguments
    # - A pydantic model as the first argument
    sig = signature(f)
    params = list(sig.parameters.values())

    standard_params = [
        param for param in params if not isinstance(param.default, Depends)
    ]

    if len(standard_params) > 1:
        raise TypeError(
            f"Function {f.__name__} must have no arguments or the first argument must be a Pydantic model."
        )

    first_argument = params[0] if len(params) > 0 else None
    action_model = first_argument.annotation if first_argument is not None else None

    if action_model is not None and not issubclass(action_model, BaseModel):
        raise TypeError(
            f"The first argument of {f.__name__} must be a Pydantic model or there should be no arguments."
        )

    if "return" not in f.__annotations__:
        raise TypeError(f"Function {f.__name__} must have a return typehint.")

    return_model = f.__annotations__["return"]

    if not (
        return_model is None
        or (isclass(return_model) and issubclass(return_model, BaseModel))
    ):
        raise TypeError(
            f"Function {f.__name__} return typehint must be None or a BaseModel."
        )

    registry_id = REGISTRY.register_action(f, action_model, return_model)

    @wraps(f)
    async def wrapper(input_body: BaseModel | None = None, *args, **kwargs):
        # We need to trap the input_model submitted to the task
        # Otherwise our run loop doesn't have access to the args once we get
        # into create_task, so they can't be delegated to other processes
        # We don't expect to actually have any args/kwargs here, but we ignore them
        # if they're provided
        return ActionExecutionStub(
            registry_id=registry_id,
            input_body=input_body,
        )

    return wrapper


async def call_action(
    registry_id: str,
    input_body: BaseModel | str | None,
):
    """
    Resolves an action from the registry and executes it
    """
    task_fn = REGISTRY.get_action(registry_id)
    task_model = REGISTRY.get_action_model(registry_id)

    # If the task model is provided, we should try to parse the inputs as the pydantic model
    task_args = []
    if task_model is not None:
        if isinstance(input_body, str):
            task_args.append(task_model.model_validate_json(input_body))
        elif isinstance(input_body, BaseModel):
            task_args.append(input_body)

    async with get_function_dependencies(callable=task_fn) as dependency_injection_args:
        return await task_fn(*task_args, **dependency_injection_args)
