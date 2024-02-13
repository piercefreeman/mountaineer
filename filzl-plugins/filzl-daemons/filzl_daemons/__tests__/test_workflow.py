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
    return payload.value + 1


@action
async def example_task_2(payload: VarInput):
    return payload.value * 2


class ExampleWorkflowInput(BaseModel):
    input_value: int


class ExampleWorkflow(Workflow[ExampleWorkflowInput]):
    async def run(self, instance: WorkflowInstance[ExampleWorkflowInput]):
        values = await asyncio.gather(
            example_task_1(VarInput(value=1)),  # 2
            example_task_1(VarInput(value=2)),  # 3
            example_task_1(VarInput(value=3)),  # 4
        )

        value_sum = sum(values)  # 9

        return await example_task_2(VarInput(i=value_sum))  # 18


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
    print("Provide engine", db_engine)
    task_manager = DaemonRunner(
        model_definitions=LOCAL_MODEL_DEFINITION,
        engine=db_engine,
        workflows=[ExampleWorkflow],
    )

    # Test that the call creates the expected instance
    await daemon_client.queue_new(ExampleWorkflow, ExampleWorkflowInput(input_value=1))

    await task_manager.handle_jobs()


def test_replay(db_engine: AsyncEngine):
    # Session interrutped halfway through and we need to start again
    # Test that we are able to play forward the event sourcing
    pass
