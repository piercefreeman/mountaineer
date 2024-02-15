import asyncio

from filzl_daemons.actions import ActionExecutionStub
from filzl_daemons.db import PostgresBackend
from filzl_daemons.logging import LOGGER
from filzl_daemons.registry import REGISTRY


class TaskManager:
    """
    Tied to the custom event loop, in charge of.
    """

    def __init__(
        self,
        backend: PostgresBackend,
    ):
        self.backend = backend

        # In-memory waits that are part of the current event loop
        # Mapping of task ID to signal
        self.wait_signals: dict[int, asyncio.Future] = {}

    async def queue_work(self, task: ActionExecutionStub):
        async with self.backend.session_maker() as session:
            action_task = self.backend.local_models.DaemonAction(
                workflow_name="todo",
                instance_id=-1,
                state="todo",
                registry_id=task.registry_id,
                input_body=(
                    task.input_body.model_dump_json() if task.input_body else None
                ),
                retry_backoff_seconds=1,
                retry_backoff_factor=1,
                retry_jitter=1,
            )
            session.add(action_task)
            await session.commit()

        # Queue work
        # We should be notified once it's completed
        # Return a signal that we can wait on
        if action_task.id is None:
            raise ValueError("Action task ID is None")

        self.wait_signals[action_task.id] = asyncio.Future()
        return self.wait_signals[action_task.id]

    async def delegate_done_actions(self):
        """
        We have waiting futures. Make sure this is running somewhere
        in the current runloop.

        """
        async for notification in self.backend.iter_ready_objects(
            model=self.backend.local_models.DaemonAction,
            queues=[],
            status="done",
        ):
            LOGGER.debug(f"Delegate done action: {notification.id}")

            # If we have no waiting futures, there's no use doing the additional roundtrips
            # to the database
            waiting_futures = self.wait_signals.get(notification.id)
            if waiting_futures is None:
                continue

            # Get the actual object
            obj = await self.backend.get_object_by_id(
                model=self.backend.local_models.DaemonAction,
                id=notification.id,
            )

            if not obj.final_result_id:
                # No result found, likely erroneous "done" setting
                LOGGER.warning(
                    f"Action {obj.id} is done, but has no final result. Skipping"
                )
                continue

            # Look for the most recent pointer
            result_obj = await self.backend.get_object_by_id(
                model=self.backend.local_models.DaemonActionResult,
                id=obj.final_result_id,
            )

            if result_obj.result_body:
                LOGGER.debug(f"Got a result: {result_obj.result_body}")
                action_model = REGISTRY.get_action_model(obj.registry_id)
                waiting_futures.set_result(
                    action_model.model_validate_json(result_obj.result_body)
                )
            elif result_obj.exception:
                LOGGER.debug(f"Got an exception: {result_obj.exception}")
                waiting_futures.set_exception(
                    Exception(
                        f"Action failed with error: {result_obj.exception} {result_obj.exception_stack}"
                    )
                )
