import asyncio
from threading import Thread
from uuid import uuid4

from filzl_daemons.actions import ActionMeta


class TaskManager:
    """
    DB bridge for getting task statuses

    One per machine, since we can distribute the results of this class
    across all subprocesses on one machine.

    """

    def __init__(self):
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
        # Infinitely blocking
        while True:
            # try to pop off the queue
            task, task_id = await self.worker_jobs.get()
            print("WORKER THREAD SHOULD HANDLE JOB", task, task_id)
            await self._simulate_task(task, task_id)


TASK_MANAGER = TaskManager()
