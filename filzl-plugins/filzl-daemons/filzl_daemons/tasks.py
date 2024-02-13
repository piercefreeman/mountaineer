import asyncio

from filzl_daemons.actions import ActionExecutionStub
from filzl_daemons.db import PostgresBackend


class TaskManager:
    """
    Tied to the custom event loop, in charge of.
    """

    def __init__(
        self,
        postgres_backend: PostgresBackend,
    ):
        self.postgres_backend = postgres_backend

        # In-memory waits that are part of the current event loop
        # Mapping of task ID to signal
        self.wait_signals = {}
        self.worker_jobs = asyncio.Queue()
        self.results = {}

    async def notify_done(self, task_id):
        """
        Simulate notifying that a task is done. In a real scenario, this might
        send a NOTIFY command to PostgreSQL, which listeners can react to.
        """
        signal = self.wait_signals.get(task_id)
        if signal:
            signal.set_result(True)
            del self.wait_signals[task_id]

    async def queue_work(self, task: ActionExecutionStub):
        # TODO: Figure out better way to pass local_model_definition
        from filzl_daemons.__tests__.conf_models import DaemonAction
        async with self.postgres_backend.session_maker() as session:
            action_task = DaemonAction(
                workflow_name="todo",
                instance_id=-1,
                state="todo",
                registry_id=task.registry_id,
                input_body=task.input_body.model_dump_json() if task.input_body else None,
            )
            session.add(action_task)
            await session.commit()

        # Queue work
        # We should be notified once it's completed
        # Return a signal that we can wait on
        self.wait_signals[action_task.id] = asyncio.Future()
        return self.wait_signals[action_task.id]

    async def delegate_done_actions(self):
        """
        We have waiting futures. Make sure this is running somewhere
        in the current runloop.

        """
        async for notification in self.postgres_backend.iter_ready_objects(
            model=self.local_model_definition.DaemonAction,
            queues=[],
            status="done",
        ):
            # Get the actual object
            obj = await self.postgres_backend.get_object_by_id(
                model=self.local_model_definition.DaemonAction,
                id=notification.id,
            )

            waiting_futures = self.wait_signals.get(notification.id)
            if waiting_futures:
                # TODO: Get the most recent result value
                waiting_futures.set_result("TODO GET VALUE")
