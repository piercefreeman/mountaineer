import asyncio

import pytest
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import Session, select

from filzl_daemons.__tests__.conf_models import (
    LOCAL_MODEL_DEFINITION,
    DaemonWorkflowInstance,
)
from filzl_daemons.actions import action
from filzl_daemons.tasks import TaskManager
from filzl_daemons.workflow import (
    DaemonClient,
    DaemonRunner,
    Workflow,
    WorkflowInstance,
)


class VarInput(BaseModel):
    value: int


@action
async def example_task_1(payload: VarInput):
    print("WILL RUN 1")
    return VarInput(value=payload.value + 1)


@action
async def example_task_2(payload: VarInput):
    print("WILL RUN 2")
    return VarInput(value=payload.value * 2)


class ExampleWorkflowInput(BaseModel):
    input_value: int


class ExampleWorkflow(Workflow[ExampleWorkflowInput]):
    async def run(self, instance: WorkflowInstance[ExampleWorkflowInput]) -> VarInput:
        values = await asyncio.gather(
            instance.run_action(
                example_task_1(VarInput(value=1)), # 2
            ),
            instance.run_action(
                example_task_1(VarInput(value=2)), # 3
            ),
            instance.run_action(
                example_task_1(VarInput(value=3)), # 4
            ),
        )

        value_sum = sum([item.value for item in values])  # 9

        return await instance.run_action(
            example_task_2(VarInput(value=value_sum))  # 18
        )


def test_workflow_creates_instance(db_engine: Engine, daemon_client: DaemonClient):
    # Test that the call creates the expected instance
    daemon_client.queue_new(ExampleWorkflow, ExampleWorkflowInput(input_value=1))

    # Test that there is one task record per each call
    with Session(db_engine) as session:
        statement = select(DaemonWorkflowInstance)
        results = list(session.exec(statement))
        assert len(results) == 1
        assert results[0].workflow_name == "ExampleWorkflow"


@pytest.mark.asyncio
async def test_workflow_runs_instance(
    db_engine: AsyncEngine, daemon_client: DaemonClient
):
    task_manager = DaemonRunner(
        model_definitions=LOCAL_MODEL_DEFINITION,
        engine=db_engine,
        workflows=[ExampleWorkflow],
    )

    result = await daemon_client.queue_new(ExampleWorkflow, ExampleWorkflowInput(input_value=1))

    timeout_task = asyncio.create_task(asyncio.sleep(5))
    wait_task = asyncio.create_task(result.wait())
    handle_jobs_task = asyncio.create_task(task_manager.handle_jobs())

    # Wait 5 seconds or until everything is done
    done, pending = await asyncio.wait(
        (
            timeout_task, wait_task, handle_jobs_task
        ),
        return_when=asyncio.FIRST_COMPLETED
    )

    # Terminate all pending tasks - this should shutdown the task manager
    for task in pending:
        task.cancel()

    assert wait_task in done
    assert timeout_task not in done

    print("DONE", done, pending)
    assert wait_task.result() == VarInput(value=18)

def test_replay(db_engine: AsyncEngine):
    # Session interrutped halfway through and we need to start again
    # Test that we are able to play forward the event sourcing
    pass
