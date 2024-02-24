import multiprocessing
from typing import Type, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from filzl_daemons.db import PostgresBackend
from filzl_daemons.tasks import TaskManager
from filzl_daemons.workflow import Workflow

T = TypeVar("T", bound=BaseModel)


class DaemonClient:
    """
    Interacts with a remote daemon pool from client code.

    """

    def __init__(
        self,
        backend: PostgresBackend,
        is_testing: bool = False,
    ):
        """
        Workflows only need to be provided if the daemon becomes a runner

        :is_testing: If true, the client will run all async actions inline with
        the queue_new, versus passing to a background worker.

        """
        self.backend = backend
        self.workflows: dict[Type[Workflow], Workflow] = {}
        self.is_testing = is_testing

    async def queue_new(self, workflow: Type[Workflow[T]], payload: T):
        """
        Client callers should call this method to queue a new task

        """
        if workflow not in self.workflows:
            self.workflows[workflow] = workflow(
                backend=self.backend,
            )

        response_future = await self.workflows[workflow].queue_task(payload)

        if self.is_testing:
            with multiprocessing.Manager() as manager:
                await self.workflows[workflow].run_handler(
                    instance_id=response_future.instance_id,
                    instance_queue="",
                    raw_input=payload.model_dump_json(),
                    task_manager=TaskManager(
                        backend=self.backend,
                        manager=manager,
                    ),
                    instance_process_id=uuid4(),
                    is_testing=True,
                )

        return response_future
