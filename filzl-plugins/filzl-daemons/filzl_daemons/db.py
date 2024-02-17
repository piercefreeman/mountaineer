import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
from typing import Type, TypeVar, cast

import asyncpg
from filzl.logging import LOGGER
from pydantic import BaseModel
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel

from filzl_daemons.models import LocalModelDefinition, QueableItemMixin, QueableStatus


class WorkflowInstanceNotification(BaseModel):
    id: int
    workflow_name: str
    status: str


T = TypeVar("T", bound=SQLModel)


class PostgresBackend:
    """
    Utilities to implement a queuing backend in postgres.

    Unlike standard sqlalchemy objects we intend for this to be pickleable / process safe.

    """

    def __init__(
        self,
        engine: AsyncEngine,
        local_models: LocalModelDefinition,
    ):
        self.engine = engine

        # Users typically want to keep objects in scope after the session commits
        # Session makers are only safe within a particular asyncio event loop
        self.session_makers: dict[
            asyncio.AbstractEventLoop, async_sessionmaker[AsyncSession]
        ] = {}

        # Async jobs are waiting for these notifications
        # Mapping of { action_id: Future }
        self.pending_notifications: dict[int, asyncio.Future] = {}

        self.local_models = local_models

    def __getstate__(self):
        # Return state to be pickled, focusing on database connection info
        # Here, we extract only the necessary components to recreate the engine
        return {
            "username": self.engine.url.username,
            "password": self.engine.url.password,
            "database": self.engine.url.database,
            "host": self.engine.url.host,
            "port": self.engine.url.port,
            "local_models": self.local_models.__getstate__(),
        }

    def __setstate__(self, state):
        # Reconstruct the object upon unpickling
        url = URL.create(
            drivername="postgresql+asyncpg",
            username=state["username"],
            password=state["password"],
            database=state["database"],
            host=state["host"],
            port=state["port"],
        )
        # Recreate the AsyncEngine with the original connection parameters
        self.engine = create_async_engine(url)
        self.session_makers = {}

        self.local_models = LocalModelDefinition.__new__(LocalModelDefinition)
        self.local_models.__setstate__(state["local_models"])

    @property
    def session_maker(self):
        # Session makers are only safe within a particular asyncio event loop
        loop = asyncio.get_event_loop()
        if loop not in self.session_makers:
            engine = create_async_engine(self.engine.url)
            self.session_makers[loop] = async_sessionmaker(
                engine, expire_on_commit=False
            )
        return self.session_makers[loop]

    async def get_object_by_id(self, model: Type[T], id: int) -> T:
        async with self.session_maker() as session:
            obj = await session.get(model, id)
            if obj is None:
                raise ValueError(f"Object with id {id} not found")
            return cast(T, obj)

    async def iter_ready_objects(
        self,
        model: Type[QueableItemMixin],
        queues: list[str],
        max_items: int | None = None,
        status: QueableStatus = QueableStatus.QUEUED,
    ):
        """
        Blocking call that will iterate over all instances as they
        become ready in the database.

        :param max_items: If supplied, will stop iterating after this amount of objects
            are returned.

        """
        retrieved_items = 0
        seen_ids = set()

        # Immediately subscribe to notifications
        notifications = self.get_instances_notification(
            queues, table_name=self.get_table_name(model), status=status
        )

        # Create a task for notifications to ensure it starts immediately
        # and doesn't block getting the backlog
        notification_task = asyncio.create_task(notifications.__anext__())

        # Process backlog
        async for value in self.get_ready_instances(
            queues, table_name=self.get_table_name(model), status=status
        ):
            obj_id = value.id
            if obj_id in seen_ids:
                continue
            seen_ids.add(obj_id)

            LOGGER.debug(f"Got ready instance: {value}")
            yield value

            retrieved_items += 1
            if max_items and retrieved_items >= max_items:
                # Ensure to cancel the notification task if max_items reached
                notification_task.cancel()
                return

        # Start consuming new notifications
        while True:
            try:
                # Wait for next notification
                value = await asyncio.wait_for(
                    asyncio.shield(notification_task), timeout=None
                )
                notification_task = asyncio.create_task(
                    notifications.__anext__()
                )  # Prepare for the next

                obj_id = value.id
                if obj_id in seen_ids:
                    continue
                seen_ids.add(obj_id)

                LOGGER.debug(f"Got instance notification: {value}")
                yield value

                retrieved_items += 1
                if max_items and retrieved_items >= max_items:
                    break
            except asyncio.CancelledError:
                # Handle cancellation properly
                break
            except StopAsyncIteration:
                # No more notifications
                break

    async def get_ready_instances(
        self,
        queues: list[str],
        table_name: str,
        status: QueableStatus,
    ):
        """
        Get the databases instances that are already ready.

        """
        optional_queue_filter = "workflow_name = ANY($1)" if queues else "TRUE"
        query = f"""
        DECLARE cur CURSOR FOR
        SELECT id, workflow_name, status
        FROM {table_name}
        WHERE {optional_queue_filter} AND status = '{status.name}'
        """
        LOGGER.debug(f"Running query: {query}")

        async with self.get_asyncpg_connection_from_engine(self.engine) as conn:
            async with conn.transaction():
                await (conn.execute(query, queues) if queues else conn.execute(query))

                async with conn.transaction():
                    while True:
                        row = await conn.fetchrow("FETCH NEXT FROM cur")
                        if row is None:
                            break
                        yield WorkflowInstanceNotification.model_validate(dict(row))

    async def get_instances_notification(
        self,
        queues: list[str],
        table_name: str,
        status: str,
    ):
        """
        Will keep looping until we have no more instances that are
        queued in the database. At this point we should subscribe/block for a NOTIFY
        signal that indicates a new task has been added to the database.

        """
        # Workaround to manually build the predicate since ANY($1) doesn't work
        # within our nested query
        queue_filters = " OR ".join(
            [f"NEW.workflow_name = '{queue_name}'" for queue_name in queues]
        )
        create_function_filter = f"({queue_filters})" if queues else "TRUE"

        unique_notifier = sha256(
            "_".join([table_name, status, *sorted(queues)]).encode()
        ).hexdigest()[:10]

        # TODO: Hash inputs of this listen for unique function names
        create_function_sql = f"""
        CREATE OR REPLACE FUNCTION notify_instance_change_{unique_notifier}()
        RETURNS TRIGGER AS $$
        BEGIN
            IF ({create_function_filter} AND NEW.status = '{status}') THEN
                PERFORM pg_notify(
                    'instance_updates_{unique_notifier}',
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

        create_trigger_sql = f"""
        CREATE OR REPLACE TRIGGER instance_update_trigger_{unique_notifier}
        AFTER INSERT OR UPDATE ON {table_name}
        FOR EACH ROW
        EXECUTE FUNCTION notify_instance_change_{unique_notifier}();
        """

        LOGGER.debug(f"Creating function: {create_function_sql}")
        LOGGER.debug(f"Creating trigger: {create_trigger_sql}")

        ready_queue: asyncio.Queue[WorkflowInstanceNotification] = asyncio.Queue()

        # Replace these values with your actual database connection details
        async with self.get_asyncpg_connection_from_engine(self.engine) as conn:
            await conn.execute(create_function_sql)
            await conn.execute(create_trigger_sql)

            async def handle_notification(
                connection: asyncpg.Connection,
                pid: int,
                channel: str,
                payload: str,
            ):
                try:
                    await ready_queue.put(
                        WorkflowInstanceNotification.model_validate_json(payload)
                    )
                except Exception as e:
                    LOGGER.exception(f"Notification parser error: {e}")
                    raise

            # Listen for the custom notification
            await conn.add_listener(
                f"instance_updates_{unique_notifier}", handle_notification
            )

        while True:
            yield await ready_queue.get()

    def get_table_name(self, model: Type[SQLModel] | SQLModel) -> str:
        table_name = model.__tablename__
        if not isinstance(table_name, str):
            raise ValueError(
                f"Table name is expected to be a string, received: {table_name}"
            )
        return table_name

    @asynccontextmanager
    async def get_asyncpg_connection_from_engine(self, engine: AsyncEngine):
        """
        Returns the asyncpg connection that backs the given SQLAlchemy async engine

        Note - This connection is still managed by SQLAlchemy, so you should not close it manually

        """
        async with engine.connect() as conn:
            raw_conn = await conn.get_raw_connection()
            if raw_conn.driver_connection is None:
                raise ValueError("Driver connection is not available")
            yield raw_conn.driver_connection
