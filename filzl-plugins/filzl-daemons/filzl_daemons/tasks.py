import asyncio

from filzl_daemons.actions import ActionExecutionStub
from filzl_daemons.db import PostgresBackend
from filzl_daemons.registry import REGISTRY


class TaskManager:
    """
    Tied to the custom event loop, in charge of.
    """

    def __init__(
        self,
        local_model_definition,
        postgres_backend: PostgresBackend,
    ):
        self.postgres_backend = postgres_backend
        self.local_model_definition = local_model_definition

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
        async with self.postgres_backend.session_maker() as session:
            action_task = self.local_model_definition.DaemonAction(
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
            print("delegate_done_actions Got a notification", notification.id)

            # If we have no waiting futures, there's no use doing the additional roundtrips
            # to the database
            waiting_futures = self.wait_signals.get(notification.id)
            if waiting_futures is None:
                continue

            # Get the actual object
            obj = await self.postgres_backend.get_object_by_id(
                model=self.local_model_definition.DaemonAction,
                id=notification.id,
            )

            # Look for the most recent pointer
            result_obj = await self.postgres_backend.get_object_by_id(
                model=self.local_model_definition.DaemonActionResult,
                id=obj.final_result_id,
            )

            if result_obj.result_body:
                print("Got a result", result_obj.result_body)
                action_model = REGISTRY.get_action_model(obj.registry_id)
                waiting_futures.set_result(
                    action_model.model_validate_json(result_obj.result_body)
                )
            elif result_obj.exception:
                print("Got an exception", result_obj.exception)
                waiting_futures.set_exception(
                    Exception(
                        f"Action failed with error: {result_obj.exception} {result_obj.exception_stack}"
                    )
                )
