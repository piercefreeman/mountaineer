import asyncio
import multiprocessing
from threading import Thread
from uuid import UUID, uuid4

from filzl.logging import LOGGER
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from filzl_daemons.actions import ActionMeta
from filzl_daemons.models import LocalModelDefinition
from filzl_daemons.worker import WorkerProcess

class TaskManager:
    """
    DB bridge for getting task statuses

    One per machine, since we can distribute the results of this class
    across all subprocesses on one machine.

    """

    def __init__(
        self,
        engine: AsyncEngine,
        local_model_definition: LocalModelDefinition,
        max_workers: int | None = None,
        threads_per_worker: int = 1,
    ):
        """
        :param max_workers: If None, we'll use the number of CPUs on the machine
        :param threads_per_worker: The number of threads to use per worker. If you have
            heavily CPU-bound tasks, keeping the default of 1 task per process is probably
            good. Otherwise in the case of more I/O bound tasks, you might want to increase
            this number.

        """
        self.max_workers = max_workers or multiprocessing.cpu_count()
        self.threads_per_worker = threads_per_worker
        self.worker_queue = multiprocessing.Queue(
            maxsize=self.max_workers * threads_per_worker
        )

        self.engine = engine
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

    def listen_to_changes(self):
        # TODO: get notified of all status updates
        # NOTIFY by postgres
        pass

    async def _simulate_task(self, task: ActionMeta, task_id):
        """
        A helper method to simulate doing some work and then notifying completion.
        """

        # Spawn a separate thread to do this work so we can still parallelize
        # tasks that might be I/O bound
        # We want each task to get a fair round-robin allocation of time
        # TODO: Maybe switch to a process pool so we can control the time that each
        # process takes and clean up resources if it times out
        def run_thread():
            async def do_work():
                # await task  # Simulate doing the task
                result = await task.func(*task.args, **task.kwargs)
                self.results[task_id] = result
                await self.notify_done(task_id)

            # run in a new, standard event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(do_work())

        # Run the thread
        thread = Thread(target=run_thread)
        thread.start()

    async def queue_work(self, task: ActionMeta):
        # Queue work
        # We should be notified once it's completed
        # Return a signal that we can wait on
        task_id = uuid4()
        self.wait_signals[task_id] = asyncio.Future()

        await self.worker_jobs.put((task, task_id))

        # Return the Future corresponding to this task_id
        return task_id, self.wait_signals[task_id]

    async def handle_jobs(self):
        # Spawn our worker processes
        worker_processes: dict[UUID, WorkerProcess] = {}
        already_drained: set[UUID] = set()

        def is_draining_callback(worker: WorkerProcess):
            # If we're alerted that the process is draining, we should
            # start a new one. Also handle the case where processes quit
            # without a draining signal.
            if worker.process_id in already_drained:
                return
            already_drained.add(worker.process_id)

            # Start a new worker to replace the one that's draining
            process = WorkerProcess(
                self.worker_queue, pool_size=self.threads_per_worker
            )
            process.add_is_draining_callback(is_draining_callback)
            process.start()
            worker_processes[process.process_id] = process

        async def health_check():
            # If the process has been terminated without a draining signal,
            # we should start a new one
            for process_id, process in list(worker_processes.items()):
                # Handle potential terminations of the process for other reasons
                if not process.is_alive():
                    is_draining_callback(process)
                del worker_processes[process_id]

            await asyncio.sleep(5)

        async def queue_work():
            while True:
                # try to pop off the queue
                task, task_id = await self.worker_jobs.get()
                LOGGER.info(f"Worker thread should handle job: {task} {task_id}")
                # await self._simulate_task(task, task_id)
                self.worker_queue.put((task, task_id))

        for _ in range(self.max_workers):
            process = WorkerProcess(
                self.worker_queue, pool_size=self.threads_per_worker
            )
            process.add_is_draining_callback(is_draining_callback)
            process.start()
            worker_processes[process.process_id] = process

        # Infinitely blocking
        await asyncio.gather(
            queue_work(),
            health_check(),
        )


# TASK_MANAGER = TaskManager()
