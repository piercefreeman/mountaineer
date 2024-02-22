# Support generic Queue[Obj] syntax
from __future__ import annotations

import asyncio
from abc import ABC, ABCMeta, abstractmethod
from datetime import datetime, timezone
from traceback import format_exc
from typing import Awaitable, Generic, Type, TypeVar, cast, get_args, get_origin
from uuid import UUID

from filzl.logging import LOGGER
from pydantic import BaseModel

from filzl_daemons.actions import ActionExecutionStub, call_action
from filzl_daemons.db import PostgresBackend
from filzl_daemons.models import QueableStatus
from filzl_daemons.registry import REGISTRY
from filzl_daemons.retry import RetryPolicy
from filzl_daemons.state import init_state, update_state
from filzl_daemons.tasks import TaskManager
from filzl_daemons.timeouts import TimeoutDefinition

T = TypeVar("T", bound=BaseModel)
K = TypeVar("K", bound=BaseModel)


class TaskException(Exception):
    pass


class WorkflowInstance(Generic[T]):
    def __init__(
        self,
        *,
        request: T,
        instance_id: int,
        instance_queue: str,
        task_manager: TaskManager,
        instance_process_id: UUID,
        is_testing: bool,
    ):
        self.request = request
        self.instance_id = instance_id
        self.instance_queue = instance_queue
        self.task_manager = task_manager
        self.instance_process_id = instance_process_id
        self.is_testing = is_testing

        self.state = init_state(request)

    async def run_action(
        self,
        action: Awaitable[K],
        *,
        retry: RetryPolicy,
        timeouts: list[TimeoutDefinition] | None = None,
        max_retries: int = 0,
    ) -> K:
        """
        Main entry point for running an action in the workflow. All calls should
        flow through your instance's run_action method.

        This method allows us to inject instance-specific metadata into
        the action.

        """
        # Execute the awaitable. If we receive a execution stub, we should queue it in
        # the backend
        result = await action

        if isinstance(result, ActionExecutionStub):
            new_state = update_state(self.state, result)
            self.state = new_state

            if self.is_testing:
                resolved_result = await self.run_inline(result)
                return cast(K, resolved_result)

            # Queue the action
            wait_future = await self.task_manager.queue_work(
                task=result,
                instance_id=self.instance_id,
                queue_name=self.instance_queue,
                state=new_state,
                retry=retry,
                instance_process_id=self.instance_process_id,
            )
            result = await wait_future
        else:
            raise ValueError(
                f"Actions must be wrapped in @action, incorrect future: {action}"
            )

        return result

    async def run_inline(self, action: ActionExecutionStub):
        """
        Run this action immediately in the main event loop; used for testing
        """
        new_state = update_state(self.state, action)
        self.state = new_state

        return await call_action(action.registry_id, action.input_body)


class WorkflowMeta(ABCMeta):
    def __init__(cls, name, bases, dct):
        super().__init__(name, bases, dct)
        REGISTRY.register_workflow(cls)  # type: ignore

        input_model: Type[BaseModel] | None = None
        output_model: Type[BaseModel] | None = None

        # We should only validate Workflow subclasses, not the Workflow class itself
        if cls.__name__ == "Workflow":
            return

        # Attempt to sniff the generic type for input_model
        for base in cls.__orig_bases__:  # type: ignore
            if (
                get_origin(base)
                and get_origin(base).__name__ == "Workflow"
                and get_args(base)
            ):
                # Make sure it's a BaseModel
                if not issubclass(get_args(base)[0], BaseModel):
                    raise TypeError(
                        f"Workflow `{cls.__name__}` must have a BaseModel as its generic type"
                    )
                input_model = get_args(base)[0]
                break

        # Sniff the run() method for its return value
        if "run" in dct:
            run_method = dct["run"]
            if not callable(run_method):
                raise TypeError(f"Workflow `{cls.__name__}` must have a run() method")
            output_model = run_method.__annotations__.get("return")

            if output_model and not issubclass(output_model, BaseModel):
                raise TypeError(
                    f"Workflow `{cls.__name__}` must have a BaseModel as its return type annotation"
                )

        if input_model is None:
            raise TypeError(
                f"Workflow `{cls.__name__}` must have a generic type annotation"
            )
        if output_model is None:
            raise TypeError(
                f"Workflow `{cls.__name__}` run() must have a return type annotation"
            )

        cls.input_model = input_model
        cls.output_model = output_model


class DaemonResponseFuture:
    def __init__(self, instance_id: int, *, backend: PostgresBackend):
        self.instance_id = instance_id
        self.backend = backend

    async def wait(self):
        """
        Performs a polling-based wait for the result of the workflow instance. Either returns
        the result or raises a TaskException if the workflow failed.

        TODO: Refactor to use notifications instead of polling

        """
        while True:
            async with self.backend.get_object_by_id(
                self.backend.local_models.DaemonWorkflowInstance,
                self.instance_id,
            ) as (instance, session):
                if instance.end_time:
                    workflow_cls = REGISTRY.get_workflow(instance.registry_id)

                    if instance.result_body is not None:
                        return workflow_cls.output_model.model_validate_json(
                            instance.result_body
                        )
                    else:
                        raise TaskException(
                            f"Workflow failed: {instance.exception}: {instance.exception_stack}"
                        )

            await asyncio.sleep(1)


class Workflow(ABC, Generic[T], metaclass=WorkflowMeta):
    input_model: Type[T]
    output_model: Type[BaseModel]

    def __init__(self, backend: PostgresBackend):
        self.backend = backend

    @abstractmethod
    async def run(self, instance: WorkflowInstance[T]) -> BaseModel:
        pass

    async def run_handler(
        self,
        instance_id: int,
        instance_queue: str,
        raw_input: str,
        task_manager: TaskManager,
        instance_process_id: UUID,
        is_testing: bool,
    ):
        try:
            request = self.input_model.model_validate_json(raw_input)

            # Call the client workflow logic
            result = await self.run(
                WorkflowInstance(
                    request=request,
                    instance_id=instance_id,
                    instance_queue=instance_queue,
                    task_manager=task_manager,
                    instance_process_id=instance_process_id,
                    is_testing=is_testing,
                )
            )

            async with self.backend.get_object_by_id(
                self.backend.local_models.DaemonWorkflowInstance,
                instance_id,
            ) as (instance, session):
                instance.status = QueableStatus.DONE
                instance.result_body = result.model_dump_json()
                instance.end_time = datetime.now(timezone.utc)
                await session.commit()
        except Exception as e:
            LOGGER.exception(f"Workflow `{self.__class__.__name__}` failed due to: {e}")

            async with self.backend.get_object_by_id(
                self.backend.local_models.DaemonWorkflowInstance,
                instance_id,
            ) as (instance, session):
                instance.status = QueableStatus.DONE
                instance.exception = str(e)
                instance.exception_stack = format_exc()
                await session.commit()

            # We want errors in testing to be noisy
            if is_testing:
                raise

    async def queue_task(self, task_input: T):
        async with self.backend.session_maker() as session:
            db_instance = self.backend.local_models.DaemonWorkflowInstance(
                workflow_name=self.__class__.__name__,
                registry_id=REGISTRY.get_registry_id_for_workflow(self.__class__),
                input_body=task_input.model_dump_json(),
                launch_time=datetime.now(timezone.utc),
            )

            session.add(db_instance)
            await session.commit()

        if db_instance.id is None:
            raise ValueError("Failed to get ID for new workflow instance")

        return DaemonResponseFuture(
            db_instance.id,
            backend=self.backend,
        )
