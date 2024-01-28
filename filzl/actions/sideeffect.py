from filzl.render import FieldClassDefinition
from typing import Callable, Type, Any
from functools import wraps
from pydantic import BaseModel
from typing import overload
from filzl.actions.fields import init_function_metadata, FunctionActionType


@overload
def sideeffect(
    # We need to typehint reload to be Any, because during typechecking our Model.attribute will just
    # yield whatever the typehint of that field is. Only at runtime does it become a FieldClassDefinition
    reload: tuple[Any, ...] | None = None,
    response_model: Type[BaseModel] | None = None,
) -> Callable[[Callable], Callable]:
    ...


@overload
def sideeffect(func: Callable) -> Callable:
    ...


def sideeffect(*args, **kwargs):
    """
    Mark a function as causing a sideeffect to the data. This will force a reload of the full (or partial) server state
    and sync these changes down to the client page.

    :reload: If provided, will ONLY reload these fields. By default will reload all fields. Otherwise, why
        specify a sideeffect at all?

    """

    def decorator_with_args(
        reload: tuple[FieldClassDefinition, ...] | None = None,
        response_model: Type[BaseModel] | None = None,
    ):
        def wrapper(func: Callable):
            @wraps(func)
            def inner(self, *func_args, **func_kwargs):
                return func(self, *func_args, **func_kwargs)

            metadata = init_function_metadata(inner, FunctionActionType.SIDEEFFECT)
            metadata.reload_states = reload
            metadata.passthrough_model = response_model
            return inner

        return wrapper

    if args and callable(args[0]):
        # It's used as @sideeffect without arguments
        func = args[0]
        return decorator_with_args()(func)
    else:
        # It's used as @sideeffect(xyz=2) with arguments
        return decorator_with_args(*args, **kwargs)
