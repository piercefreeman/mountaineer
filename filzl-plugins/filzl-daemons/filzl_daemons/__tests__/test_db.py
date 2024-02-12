from sqlalchemy.ext.asyncio import AsyncEngine
from filzl_daemons.db import PostgresBackend
from filzl_daemons.__tests__.conf_models import DaemonWorkflowInstance
import pytest
from datetime import datetime
import asyncio

@pytest.mark.asyncio
async def test_iter_ready_objects(db_engine: AsyncEngine):
    postgres_backend = PostgresBackend(engine=db_engine)

    # Create one object before we run the notification loop to test
    # if we're able to retrieve already-created objects
    async with postgres_backend.session_maker() as session:
        session.add(
            DaemonWorkflowInstance(
                id=10,
                workflow_name="test_workflow_id",
                task_input="value_1".encode(),
                launch_time=datetime.now(),
            )
        )
        await session.commit()

    async def create_object():
        await asyncio.sleep(0.1)

        async with postgres_backend.session_maker() as session:
            session.add(
                DaemonWorkflowInstance(
                    id=20,
                    workflow_name="test_workflow_id",
                    task_input="value_2".encode(),
                    launch_time=datetime.now(),
                )
            )
            await session.commit()

    async def read_objects():
        items = []
        async for item in postgres_backend.iter_ready_objects(
            model=DaemonWorkflowInstance,
            queues=["test_workflow_id"],
            max_items=1,
        ):
            items.append(item)

        return items

    _, found_items = await asyncio.gather(create_object(), read_objects())
    assert len(found_items) == 2
    assert found_items[0].id == 10
    assert found_items[1].id == 20
