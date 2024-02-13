import asyncio
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from filzl_daemons.__tests__.conf_models import (
    LOCAL_MODEL_DEFINITION,
    DaemonWorkflowInstance,
)
from filzl_daemons.db import PostgresBackend


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit_queues",
    [
        # Should work with both isolated filtering and no filtering (global view)
        (["test_workflow_id"]),
        ([]),
    ],
)
async def test_iter_ready_objects(db_engine: AsyncEngine, limit_queues: list[str]):
    postgres_backend = PostgresBackend(
        engine=db_engine,
        local_models=LOCAL_MODEL_DEFINITION,
    )

    # Create one object before we run the notification loop to test
    # if we're able to retrieve already-created objects
    async with postgres_backend.session_maker() as session:
        session.add(
            DaemonWorkflowInstance(
                id=10,
                workflow_name="test_workflow_id",
                registry_id="test_registry_id",
                input_body="value_1",
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
                    registry_id="test_registry_id",
                    input_body="value_2",
                    launch_time=datetime.now(),
                )
            )
            await session.commit()

    async def read_objects():
        items = []
        async for item in postgres_backend.iter_ready_objects(
            model=DaemonWorkflowInstance,
            queues=limit_queues,
            max_items=2,
        ):
            items.append(item)

        return items

    _, found_items = await asyncio.gather(create_object(), read_objects())
    assert len(found_items) == 2
    assert found_items[0].id == 10
    assert found_items[1].id == 20
