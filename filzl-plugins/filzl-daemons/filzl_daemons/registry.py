import sys
from importlib import import_module
from itertools import chain
from typing import TYPE_CHECKING, Callable, Type

from pydantic import BaseModel

if TYPE_CHECKING:
    from filzl_daemons.workflow import Workflow


class FunctionMetadata(BaseModel):
    function_name: str
    func: Callable
    module: str
    input_model: Type[BaseModel] | None


class WorkflowMetadata(BaseModel):
    workflow_name: str
    workflow: Callable
    module: str


class ActionRegistry:
    """
    Note that the registry is tied to each process. Worker processes
    will have to ensure that things are brought back into scope.

    """

    def __init__(self):
        self.action_registry: dict[str, FunctionMetadata] = {}
        self.workflow_registry: dict[str, WorkflowMetadata] = {}

    def get_modules_in_registry(self) -> list[str]:
        """
        Returns a picklable set of modules that are in the registry.
        Can be mounted to another processes' registry by calling import_modules.
        """
        return list(
            {
                action_meta.module
                for action_meta in chain(
                    self.action_registry.values(),
                    self.workflow_registry.values(),
                )
            }
        )

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
        return self.action_registry[registry_id].func

    def get_action_model(self, registry_id: str) -> Type[BaseModel] | None:
        """
        Given the output of `get_registry_id_for_action`, returns the
        input model if registered within the current registry.

        """
        return self.action_registry[registry_id].input_model

    def get_workflow(self, registry_id: str) -> Type["Workflow"]:
        """
        Returns the workflow (the class itself) for the given registry_id.

        """
        print("REGISTRY", self.workflow_registry)
        return self.workflow_registry[registry_id].workflow

    def register_action(self, action: Callable, input_model: Type[BaseModel] | None):
        """
        Registers a new action into the registry and responds with a unique
        identifier to retrieve the full action definition from the registry.

        """
        registry_id = self.get_registry_id_for_action(action)

        if registry_id in self.action_registry:
            raise Exception(
                f"Another function {action.__name__} is already in the registry, action names must be globally unique."
            )

        self.action_registry[registry_id] = FunctionMetadata(
            function_name=action.__name__,
            func=action,
            module=action.__module__,
            input_model=input_model,
        )

        return registry_id

    def register_workflow(self, workflow: Type["Workflow"]):
        print("SHOULD REGISTER WORKFLOW", workflow)
        registry_id = self.get_registry_id_for_workflow(workflow)

        if registry_id in self.workflow_registry:
            raise Exception(
                f"Another workflow {workflow.__name__} is already in the registry, workflow names must be globally unique."
            )

        self.workflow_registry[registry_id] = WorkflowMetadata(
            workflow_name=workflow.__name__,
            workflow=workflow,
            module=workflow.__module__,
        )

    @staticmethod
    def get_registry_id_for_action(action: Callable) -> str:
        # This function must be deterministic given an action called from
        # any process.
        return f"{action.__module__}.{action.__name__}"

    @staticmethod
    def get_registry_id_for_workflow(workflow: Type["Workflow"]) -> str:
        return f"{workflow.__module__}.{workflow.__name__}"


REGISTRY = ActionRegistry()
