import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from filzl.logging import LOGGER
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlmodel import select

from filzl_daemons.__tests__.conf_models import (
    DaemonWorkflowInstance,
)
from filzl_daemons.actions import action
from filzl_daemons.db import PostgresBackend
from filzl_daemons.models import QueableStatus
from filzl_daemons.retry import RetryPolicy
from filzl_daemons.workflow import (
    DaemonClient,
    DaemonRunner,
    Workflow,
    WorkflowInstance,
)


class VarInput(BaseModel):
    value: int


@action
async def example_task_1(payload: VarInput) -> VarInput:
    LOGGER.info(f"example_task_1: {payload.value}")
    return VarInput(value=payload.value + 1)


@action
async def example_task_2(payload: VarInput) -> VarInput:
    LOGGER.info(f"example_task_2: {payload.value}")
    return VarInput(value=payload.value * 2)


class ExampleWorkflowInput(BaseModel):
    input_value: int


class ExampleWorkflow(Workflow[ExampleWorkflowInput]):
    async def run(self, instance: WorkflowInstance[ExampleWorkflowInput]) -> VarInput:
        values = await asyncio.gather(
            instance.run_action(
                example_task_1(VarInput(value=1)),  # 2
                retry=RetryPolicy(),
            ),
            instance.run_action(
                example_task_1(VarInput(value=2)),  # 3
                retry=RetryPolicy(),
            ),
            instance.run_action(
                example_task_1(VarInput(value=3)),  # 4
                retry=RetryPolicy(),
            ),
        )

        value_sum = sum([item.value for item in values])  # 9

        return await instance.run_action(
            example_task_2(VarInput(value=value_sum)),  # 18
            retry=RetryPolicy(),
        )


@pytest.mark.asyncio
async def test_workflow_creates_instance(
    db_engine: AsyncEngine, daemon_client: DaemonClient
):
    # Test that the call creates the expected instance
    await daemon_client.queue_new(ExampleWorkflow, ExampleWorkflowInput(input_value=1))

    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)

    # Test that there is one task record per each call
    async with session_maker() as session:
        statement = select(DaemonWorkflowInstance)
        result = await session.execute(statement)
        results = result.scalars().all()
        assert len(results) == 1
        assert results[0].workflow_name == "ExampleWorkflow"


@pytest.mark.asyncio
async def test_workflow_runs_instance(
    postgres_backend: PostgresBackend, daemon_client: DaemonClient
):
    task_manager = DaemonRunner(
        workflows=[ExampleWorkflow],
        backend=postgres_backend,
    )

    result = await daemon_client.queue_new(
        ExampleWorkflow, ExampleWorkflowInput(input_value=1)
    )

    timeout_task = asyncio.create_task(asyncio.sleep(5))
    wait_task = asyncio.create_task(result.wait())
    handle_jobs_task = asyncio.create_task(task_manager.handle_jobs())

    # Wait 5 seconds or until everything is done
    done, pending = await asyncio.wait(
        (timeout_task, wait_task, handle_jobs_task), return_when=asyncio.FIRST_COMPLETED
    )

    # Terminate all pending tasks - this should shutdown the task manager
    for task in pending:
        task.cancel()

    assert wait_task in done
    assert timeout_task not in done

    assert wait_task.result() == VarInput(value=18)


def test_parse_workflow_meta():
    """
    Ensure that our metaclass can take the typehints of a workflow definition and
    parse them into the model base.

    """

    class InputItem(BaseModel):
        input_value: int

    class OutputItem(BaseModel):
        output_value: int

    class WorkflowWithTypehints(Workflow[InputItem]):
        async def run(self, instance: WorkflowInstance[InputItem]) -> OutputItem:
            return OutputItem(output_value=1)

    assert WorkflowWithTypehints.input_model == InputItem
    assert WorkflowWithTypehints.output_model == OutputItem


def test_parse_workflow_missing_meta():
    """
    Test errors flagged when exceptions are mis-identified.

    """

    class InputItem(BaseModel):
        input_value: int

    class OutputItem(BaseModel):
        output_value: int

    with pytest.raises(TypeError):

        class WorkflowWithTypehints1(Workflow):
            async def run(self, instance: WorkflowInstance) -> OutputItem:
                return OutputItem(output_value=1)

    with pytest.raises(TypeError):

        class WorkflowWithTypehints2(Workflow[InputItem]):
            async def run(self, instance: WorkflowInstance[InputItem]):
                return OutputItem(output_value=1)


@pytest.mark.asyncio
async def test_update_timed_out_tasks(
    postgres_backend: PostgresBackend,
):
    # Set up: a timed out worker, a timed out action, and a timed out instance
    # In practice actions and instances will be handled by different workers, but there's
    # nothing at the DB or logic level that requires this to be true
    async with postgres_backend.session_maker() as session:
        worker_status = postgres_backend.local_models.WorkerStatus(
            internal_process_id=uuid4(),
            launch_time=datetime.now() - timedelta(minutes=20),
            last_ping=datetime.now() - timedelta(minutes=10),
        )
        session.add(worker_status)
        await session.commit()

        action = postgres_backend.local_models.DaemonAction(
            workflow_name="ExampleWorkflow",
            instance_id=1,
            state="",
            status=QueableStatus.IN_PROGRESS,
            registry_id="",
            input_body="",
            retry_backoff_seconds=0,
            retry_backoff_factor=0,
            retry_jitter=0,
            assigned_worker_status_id=worker_status.id,
        )
        session.add(action)

        instance = postgres_backend.local_models.DaemonWorkflowInstance(
            workflow_name="ExampleWorkflow",
            registry_id="",
            input_body="",
            launch_time=datetime.now(),
            assigned_worker_status_id=worker_status.id,
        )
        session.add(instance)

        await session.commit()

        task_manager = DaemonRunner(
            workflows=[ExampleWorkflow],
            backend=postgres_backend,
        )

        await task_manager._update_timed_out_workers_single(5)

        # Update the worker status to be recent
        await session.refresh(worker_status)
        await session.refresh(action)
        await session.refresh(instance)

        assert worker_status.cleaned_up
        assert action.status == QueableStatus.QUEUED
        assert instance.status == QueableStatus.QUEUED


def test_replay(db_engine: AsyncEngine):
    # Session interrutped halfway through and we need to start again
    # Test that we are able to play forward the event sourcing
    pass
