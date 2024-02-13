# from abc import ABC, abstractmethod
# from hashlib import sha256
# from typing import Any, Awaitable, Callable, Generic, Optional, TypeVar

# from pydantic import BaseModel

# from filzl_daemons.actions import ActionMetadata


# class StateUpdate(BaseModel):
#     fn_name: str
#     args: list[Any]
#     kwargs: dict[str, Any]


# class DameonValueUnset(BaseModel):
#     """
#     Sentinal value to indicate that the value is not set
#     """

#     pass


# class CurrentState(BaseModel):
#     """
#     TODO: Database object
#     """

#     state: str

#     fn: ActionMetadata

#     previous_state: Optional["CurrentState"] = None
#     next_state: Optional["CurrentState"] = None

#     # Once the action has completed successfully
#     resolved_value: Any | None | DameonValueUnset = DameonValueUnset()


# class Job(BaseModel):
#     """
#     One execution of a workflow run, may have a failure
#     """

#     # Primary key indexed
#     id: int


# T = TypeVar("T", bound=BaseModel)

# ActionReturn = TypeVar("ActionReturn")


# class WorkflowInstance(Generic[T]):
#     """
#     Wraps one execution of a workflow run.

#     """

#     current_state: CurrentState
#     input_payload: T

#     def __init__(self, workflow: "Workflow", input_payload: T):
#         self.workflow = workflow

#         # Initial state to start the event source chain
#         self.state = CurrentState(
#             state=sha256(input_payload.model_dump_json().encode()).hexdigest(),
#             fn=ActionMetadata(
#                 fn=None,
#                 args=[],
#                 kwargs={},
#             ),
#         )

#     async def run_action(
#         self, fn: Callable[..., Awaitable[ActionReturn]]
#     ) -> ActionReturn:
#         # Ensure this function is actually decorated with an @action
#         # if not hasattr(fn, "metadata"):
#         #    print(fn.__name__, fn, fn.__dict__)
#         #    raise ValueError("Function must be decorated with @action")

#         # TODO: Special case for asyncio.sleep

#         # Has the current state, in charge of running the action
#         # every time this runs it will permute the state in the same
#         # expected way
#         # This supports rollup events like gather() since this will permute
#         # the state for every input
#         # TODO: Add to another worker

#         # Determine if this task has already been queued, if so we should wait for it
#         pass

#         return await fn

#     def update_state(self, metadata: ActionMetadata):
#         # Just use the function's name as the hash value for now
#         state_update = StateUpdate(
#             fn_name=metadata.fn.__name__,
#             args=metadata.args,
#             kwargs=metadata.kwargs,
#         )

#         state_hash = state_update.model_dump_json()
#         current_state = sha256(
#             (self.current_state.state + state_hash).encode()
#         ).hexdigest()

#         new_state = CurrentState(
#             state=current_state,
#             fn=metadata,
#             previous_state=self.current_state,
#         )
#         self.current_state.next_state = new_state
#         self.current_state = new_state

#         return self.current_state


# class Workflow(ABC):
#     """
#     Wraps a full workflow handler. This __init__ will only be called
#     once per worker spawn. It's expected to handle multiple WorkflowInstances.

#     Metadata is not guaranteed to persist across either Workflow or WorkflowInstance. Any
#     metadata that needs to persist should be stored in the database as part
#     of an action query.

#     """

#     def __init__(self):
#         # In-memory queue, switch to a database queue
#         self.instance_queue: list[WorkflowInstance] = []
#         # TODO: Database-backed
#         # self.dependencies :

#     @abstractmethod
#     async def run(self, instance: WorkflowInstance[T]):
#         pass

#     def queue(self, input_value: T):
#         """
#         Queue a new value for execution
#         """
#         instance = WorkflowInstance(self, input_value)
#         self.instance_queue.append(instance)
