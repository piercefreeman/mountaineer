from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import Session, select
from filzl_daemons.actions import action
import asyncio
from filzl_daemons.workflow import Daemon, Workflow, WorkflowInstance
from filzl_daemons.__tests__.conf_models import DaemonWorkflowInstance, LOCAL_MODEL_DEFINITION
from filzl_daemons.tasks import TaskManager
from sqlalchemy.ext.asyncio import AsyncEngine
import pytest

@action
async def example_task_1(i: int):
    return i + 1

async def example_task_2(i: int):
    return i * 2

class ExampleWorkflowInput(BaseModel):
    input_value: int

class ExampleWorkflow(Workflow[ExampleWorkflowInput]):
    async def run(self, instance: WorkflowInstance[ExampleWorkflowInput]):
        values = await asyncio.gather(
            example_task_1(1), # 2
            example_task_1(2), # 3
            example_task_1(3), # 4
        )

        value_sum = sum(values) # 9

        return await example_task_2(value_sum) # 18

def test_workflow_creates_instance(db_engine: Engine, daemon_client: Daemon):
    # Test that the call creates the expected instance
    daemon_client.queue_new(
        ExampleWorkflow,
        ExampleWorkflowInput(input_value=1)
    )

    # Test that there is one task record per each call
    with Session(db_engine) as session:
        statement = select(DaemonWorkflowInstance)
        results = list(session.exec(statement))
        assert len(results) == 1
        assert results[0].workflow_name == "ExampleWorkflow"

@pytest.mark.asyncio
async def test_workflow_runs_instance(db_engine: AsyncEngine, daemon_client: Daemon):
    print("Provide engine", db_engine)
    task_manager = TaskManager(
        engine=db_engine,
        local_model_definition=LOCAL_MODEL_DEFINITION,
    )

    async def handle_pending_instances():
        # wait for the first object to be created
        await asyncio.sleep(1)
        async for val in task_manager.iter_ready_instances(
            [
                ExampleWorkflow.__name__,
            ]
        ):
            print("VAL", val)


    async def create_instances():
        # Test that the call creates the expected instance
        await daemon_client.queue_new(
            ExampleWorkflow,
            ExampleWorkflowInput(input_value=1)
        )
        print("did create 1")

        await asyncio.sleep(2)

        await daemon_client.queue_new(
            ExampleWorkflow,
            ExampleWorkflowInput(input_value=2)
        )
        print("did create 2")
        await asyncio.sleep(2)
        print("Done")

    await asyncio.gather(
        handle_pending_instances(),
        create_instances(),
    )
    # We can re-use the same client as our runner
    #daemon_client.

def test_replay(db_engine: AsyncEngine):
    # Session interrutped halfway through and we need to start again
    # Test that we are able to play forward the event sourcing
    pass
