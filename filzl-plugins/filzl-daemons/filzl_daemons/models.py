import sys
from datetime import datetime, timezone
from enum import StrEnum
from importlib import import_module
from inspect import isclass
from typing import Type, TypeVar
from uuid import UUID

from filzl.sqlmodel import Field, SQLModel
from sqlalchemy import DateTime


class QueableStatus(StrEnum):
    # Ensure keys and values are mirrored in value / case, since some of our sqlalchemy integration
    # implicitly uses the key and others use the value.
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    SCHEDULED = "SCHEDULED"


def utc_now():
    return datetime.now(timezone.utc)


class QueableItemMixin(SQLModel):
    """
    Mixin for items that can be queued.
    """

    workflow_name: str
    status: QueableStatus = QueableStatus.QUEUED

    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"default": utc_now, "onupdate": utc_now},
    )


class DaemonWorkflowInstance(QueableItemMixin, SQLModel):
    """
    One given instance of a workflow execution.
    """

    id: int | None = Field(default=None, primary_key=True)

    # Will couple with the defined Workflow
    registry_id: str
    input_body: str  # json input

    # Status metadata
    launch_time: datetime = Field(
        sa_type=DateTime(timezone=True),
    )
    end_time: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
    )
    assigned_worker_status_id: int | None = None

    # Exit status
    exception: str | None = None
    exception_stack: str | None = None
    result_body: str | None = None


class WorkerStatus(SQLModel):
    """
    Current status of the worker.
    """

    id: int | None = Field(default=None, primary_key=True)

    # Internal process ID generated by each worker
    internal_process_id: UUID

    is_action_worker: bool = False
    is_instance_worker: bool = False
    is_draining: bool = False

    launch_time: datetime = Field(sa_type=DateTime(timezone=True))
    last_ping: datetime = Field(sa_type=DateTime(timezone=True))

    # If the worker exits, our supervisor should clean up dependent actions. If this
    # value is set, this indicates that a supervisor has already completed the cleanup.
    cleaned_up: bool = False


class DaemonAction(QueableItemMixin, SQLModel):
    """
    One given action call, can potentially have multiple repeats depending on the backoff event.
    """

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        sa_type=DateTime(timezone=True), default_factory=utc_now
    )

    instance_id: int

    # Event-sourced state identifier, will be mirrored across multiple instance runs if necessary
    state: str

    registry_id: str
    input_body: str | None  # json payload

    # When the latest execution of this action was started
    started_datetime: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
    )
    assigned_worker_status_id: int | None = None
    ended_datetime: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
    )

    # Retry metadata, must be set in the instantiation of each action
    retry_current_attempt: int = 0
    retry_max_attempts: int | None = None
    retry_backoff_seconds: int
    retry_backoff_factor: float
    retry_jitter: float

    # The most recent DaemonActionResult. If there is an exit condition like retry_max_attempts,
    # this will be the final result.
    final_result_id: int | None = None

    # Timeout preferences, in seconds
    wall_soft_timeout: int | None = None
    wall_hard_timeout: int | None = None
    cpu_soft_timeout: int | None = None
    cpu_hard_timeout: int | None = None

    # Don't schedule before this time interval
    schedule_after: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
    )


class DaemonActionResult(SQLModel):
    """
    Represents the potentially one:many executions of the daemon actions.
    """

    id: int | None = Field(default=None, primary_key=True)
    action_id: int
    instance_id: int

    attempt_num: int
    finished_at: datetime = Field(
        sa_type=DateTime(timezone=True),
    )

    # Exit status
    exception: str | None = None
    exception_stack: str | None = None
    result_body: str | None = None


DaemonWorkflowInstanceType = TypeVar(
    "DaemonWorkflowInstanceType", bound=DaemonWorkflowInstance
)
WorkerStatusType = TypeVar("WorkerStatusType", bound=WorkerStatus)
DaemonActionType = TypeVar("DaemonActionType", bound=DaemonAction)
DaemonActionResultType = TypeVar("DaemonActionResultType", bound=DaemonActionResult)


class LocalModelDefinition:
    """
    Wrapper class to let downstream clients
    define their own model types.
    """

    def __init__(
        self,
        DaemonWorkflowInstance: Type[DaemonWorkflowInstanceType],
        WorkerStatus: Type[WorkerStatusType],
        DaemonAction: Type[DaemonActionType],
        DaemonActionResult: Type[DaemonActionResultType],
    ):
        self.DaemonWorkflowInstance = DaemonWorkflowInstance
        self.WorkerStatus = WorkerStatus
        self.DaemonAction = DaemonAction
        self.DaemonActionResult = DaemonActionResult

    def __getstate__(self):
        # Find the modules that implement these different models
        return {
            key: value.__module__
            for key, value in self.__dict__.items()
            if isclass(value) and issubclass(value, SQLModel)
        }

    def __setstate__(self, state):
        # Dynamically import the modules that implement these different models
        for key, module in state.items():
            if module not in sys.modules:
                imported_module = import_module(module)
            else:
                imported_module = sys.modules[module]
            setattr(self, key, getattr(imported_module, key))
