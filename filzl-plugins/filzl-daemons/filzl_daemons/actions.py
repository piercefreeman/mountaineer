from functools import wraps
from typing import Any, Callable

from pydantic import BaseModel
import sys
from importlib import import_module
from inspect import iscoroutinefunction

class FunctionMetadata(BaseModel):
    function_name: str
    func: Callable
    module: str

class ActionMeta(BaseModel):
    registry_id: str
    args: tuple[Any] = tuple()
    kwargs: dict[str, Any] = {}

def action(f):
    global REGISTRY

    print(f"Adding to registry: {f.__name__}")
    registry_id = REGISTRY.register_action(f)

    # Require the function to be async
    if not iscoroutinefunction(f):
        raise Exception(
            f"Function {f.__name__} is not a coroutine function. Use async def instead of def."
        )

    @wraps(f)
    async def wrapper(*args, **kwargs):
        # We need to trap the args and kwargs
        # Otherwise our run loop doesn't have access to the args once we get
        # into create_task, so they can't be delegated to other processes
        return ActionMeta(
            registry_id=registry_id,
            args=args,
            kwargs=kwargs,
        )

    return wrapper

class ActionRegistry:
    """
    Note that the registry is tied to each process. Worker processes
    will have to ensure that things are brought back into.

    """
    def __init__(self):
        self.registry : dict[str, FunctionMetadata] = {}

    def get_modules_in_registry(self) -> list[str]:
        """
        Returns a picklable set of modules that are in the registry.
        Can be mounted to another processes' registry by calling import_modules.
        """
        return list({
            action_meta.module for action_meta in self.registry.values()
        })

    def load_modules(self, modules: list[str]):
        """
        Imports all modules that contain registered actions to ensure
        that the actions are available in the current namespace.

        """
        for module in modules:
            if module not in sys.modules:
                import_module(module)

    def get_action(self, registry_id: str) -> Callable:
        """
        Given the output of `get_registry_id_for_action`, returns the
        action function if registered within the current registry.

        """
        return self.registry[registry_id].func

    def register_action(self, action: Callable):
        """
        Registers a new action into the registry and responds with a unique
        identifier to retrieve the full action definition from the registry.

        """
        registry_id = self.get_registry_id_for_action(action)

        if registry_id in self.registry:
            raise Exception(f"Another function {action.__name__} is already in the registry, action names must be globally unique.")

        self.registry[registry_id] = FunctionMetadata(
            function_name=action.__name__,
            func=action,
            module=action.__module__,
        )

        return registry_id

    @staticmethod
    def get_registry_id_for_action(action: Callable) -> str:
        # This function must be deterministic given an action called from
        # any process.
        return f"{action.__module__}.{action.__name__}"

REGISTRY = ActionRegistry()
