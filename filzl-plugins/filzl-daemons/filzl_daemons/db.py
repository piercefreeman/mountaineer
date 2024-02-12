import asyncio
from contextlib import asynccontextmanager
from typing import Type

import asyncpg
from filzl.logging import LOGGER
from sqlalchemy.ext.asyncio import AsyncEngine, async_engine_from_config
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from pydantic import BaseModel
from filzl_daemons.models import QueableItemMixin



class WorkflowInstanceNotification(BaseModel):
    id: int
    workflow_name: str
    status: str


class PostgresBackend:
    """
    Utilities to implement a queuing backend in postgres.

    """
    def __init__(self, engine: AsyncEngine):
        self.engine = engine

        # Users typically want to keep objects in scope after the session commits
        self.session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def iter_ready_objects(
        self,
        model: Type[QueableItemMixin],
        queues: list[str],
        max_items: int | None = None,
    ):
        """
        Blocking call that will iterate over all instances as they
        become ready in the database.

        :param max_items: If supplied, will stop iterating after this amount of objects
            are returned.

        """
        retrieved_items = 0

        print("---- READY NOW ----")
        async for value in self.get_ready_instances(queues):
            yield value

            retrieved_items += 1
            if max_items and retrieved_items >= max_items:
                break

        print("---- READY FUTURE ----")
        async for value in self.get_instances_notification(queues):
            yield value

            retrieved_items += 1
            if max_items and retrieved_items >= max_items:
                break

    async def get_ready_instances(self, queues: list[str]):
        """
        Get the databases instances that are already ready.

        """
        query = """
        DECLARE cur CURSOR FOR
        SELECT id, workflow_name, status
        FROM daemonworkflowinstance
        WHERE workflow_name = ANY($1) AND status = 'queued'
        """

        async with self.get_asyncpg_connection_from_engine(self.engine) as conn:
            async with conn.transaction():
                await conn.execute(query, queues)

                async with conn.transaction():
                    while True:
                        row = await conn.fetchrow("FETCH NEXT FROM cur")
                        if row is None:
                            break
                        yield WorkflowInstanceNotification.model_validate(dict(row))

    async def get_instances_notification(self, queues: list[str]):
        """
        Will keep looping until we have no more instances that are
        queued in the database. At this point we should subscribe/ block for a NOTIFY
        signal that indicates a new task has been added to the database.

        """
        create_function_queue_names = " OR ".join(
            [f"NEW.workflow_name = '{queue_name}'" for queue_name in queues]
        )
        create_function_sql = f"""
        CREATE OR REPLACE FUNCTION notify_instance_change()
        RETURNS TRIGGER AS $$
        BEGIN
            IF (({create_function_queue_names}) AND NEW.status = 'queued') THEN
                PERFORM pg_notify(
                    'instance_updates',
                    json_build_object(
                        'id', NEW.id,
                        'workflow_name', NEW.workflow_name,
                        'status', NEW.status
                    )::text
                );
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """

        create_trigger_sql = """
        CREATE TRIGGER instance_update_trigger
        AFTER INSERT OR UPDATE ON daemonworkflowinstance
        FOR EACH ROW
        EXECUTE FUNCTION notify_instance_change();
        """

        ready_queue: asyncio.Queue[WorkflowInstanceNotification] = asyncio.Queue()

        # Replace these values with your actual database connection details
        async with self.get_asyncpg_connection_from_engine(self.engine) as conn:
            print("CONN", conn)

            await conn.execute(create_function_sql)
            print("Trigger function created successfully.")

            await conn.execute(create_trigger_sql)
            print("Trigger created successfully.")

            async def handle_notification(
                connection: asyncpg.Connection,
                pid: int,
                channel: str,
                payload: str,
            ):
                try:
                    print("HANDLE NOTIFICATION", payload)
                    await ready_queue.put(
                        WorkflowInstanceNotification.model_validate_json(payload)
                    )
                except Exception as e:
                    LOGGER.exception(f"ERROR: {e}")
                    raise

            # Listen for the custom notification
            await conn.add_listener("instance_updates", handle_notification)

        while True:
            print("WAITING FOR NOTIFICATION")
            yield await ready_queue.get()

    @asynccontextmanager
    async def get_asyncpg_connection_from_engine(self, engine: AsyncEngine) -> asyncpg.Connection:
        """
        Returns the asyncpg connection that backs the given SQLAlchemy async engine

        Note - This connection is still managed by SQLAlchemy, so you should not close it manually

        """
        async with engine.connect() as conn:
            raw_conn = await conn.get_raw_connection()
            yield raw_conn.driver_connection
