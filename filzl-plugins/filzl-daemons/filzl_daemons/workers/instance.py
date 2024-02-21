import asyncio
from dataclasses import dataclass
from threading import Thread
from typing import TYPE_CHECKING
from uuid import uuid4

from filzl_daemons.db import PostgresBackend
from filzl_daemons.io import AsyncMultiprocessingQueue, safe_task
from filzl_daemons.registry import REGISTRY
from filzl_daemons.tasks import TaskManager
from filzl_daemons.workers.base import WorkerBase

if TYPE_CHECKING:
    from filzl_daemons.workflow import Workflow


@dataclass
class InstanceTaskDefinition:
    instance_id: int
    registry_id: str
    queue_name: str
    raw_input: str


class InstanceWorkerProcess(WorkerBase):
    def __init__(
        self,
        task_queue: AsyncMultiprocessingQueue[InstanceTaskDefinition],
        backend: PostgresBackend,
        task_manager: TaskManager,
        pool_size: int,
    ):
        super().__init__(backend=backend)

        self.task_queue = task_queue
        self.backend = backend
        self.task_manager = task_manager
        self.process_id = uuid4()
        self.pool_size = pool_size

        self.custom_worker_args["is_instance_worker"] = True

        self.action_modules = REGISTRY.get_modules_in_registry()

    def worker_init(self):
        super().worker_init()

        self.pool_semaphore = asyncio.Semaphore(self.pool_size)

        # {registry_id: WorkflowBase}
        # Cached at the process level to avoid repeating heavy init loads
        self.cached_workflows: dict[str, "Workflow"] = {}

        # Load back the modules into the new process's registry
        REGISTRY.load_modules(self.action_modules)

    def run(self):
        asyncio.run(self.run_async())

    async def run_async(self):
        self.worker_init()

        ping_thread = Thread(target=self.ping, daemon=True)
        ping_thread.start()

        await asyncio.gather(
            safe_task(self.monitor_new_queue)(),
            safe_task(self.task_manager.worker_receive_done_action)(self.process_id),
        )

    async def monitor_new_queue(self):
        while True:
            # Acquire a slot in the pool before we get the task, to prevent dequeuing
            # it and not being able to resolve a valid spot
            await self.pool_semaphore.acquire()

            task = await self.task_queue.async_get()
            if task is None:
                break

            self.handle_instance(task)

    def handle_instance(self, task: InstanceTaskDefinition):
        """
        Workflow run() functions are expected to mainly be outbound calls to the
        action workers to process data in bulk. As such we feel comfortable adding all
        the instances to the common asyncio runloop of this process.

        """
        if task.registry_id not in self.cached_workflows:
            workflow_cls = REGISTRY.get_workflow(task.registry_id)
            self.cached_workflows[task.registry_id] = workflow_cls(backend=self.backend)

        workflow = self.cached_workflows[task.registry_id]

        asyncio.create_task(self.run_handler_wrapper(workflow, task))

    async def run_handler_wrapper(
        self, workflow: "Workflow", task: InstanceTaskDefinition
    ):
        try:
            await workflow.run_handler(
                instance_id=task.instance_id,
                instance_queue=task.queue_name,
                raw_input=task.raw_input,
                task_manager=self.task_manager,
                instance_process_id=self.process_id,
            )
        finally:
            self.pool_semaphore.release()
