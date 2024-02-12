import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from multiprocessing import Process, Queue
from queue import Empty, Full
from threading import Lock, Semaphore, Thread
from time import sleep
from typing import Callable
from uuid import UUID, uuid4

from filzl_daemons import filzl_daemons as filzl_daemons_rs  # type: ignore
from filzl_daemons.actions import REGISTRY
from filzl_daemons.logging import LOGGER
from filzl_daemons.timeouts import TimeoutDefinition, TimeoutType, TimeoutMeasureType

@dataclass
class TaskDefinition:
    registry_id: str
    args: list
    kwargs: dict
    timeouts: list[TimeoutDefinition]


@dataclass
class ThreadDefinition:
    thread_id: UUID
    thread: Thread | None
    started_wall: datetime
    timeouts: list[TimeoutDefinition]

    # Flagged when any timeout is triggered, allows internal handlers to try
    # and clean up gracefully
    timed_out_causes: set[TimeoutType] = field(default_factory=set)


class WorkerProcess(Process):
    """
    We support setting a max time for each task. This max time measures
    the amount of time that the task has actually been executing by
    the CPU.

    Our approach relies on a soft-timeout (which is the user specified time limit)
    and then a hard-timeout (by default a minute after the user specified interval). The
    soft timeout attempts to stop the task by canceling the outstanding async runloop. This works
    if the task has a lot of asyncs that return control to the runloop. If the task is saturating
    the CPU and not returning control to the runloop, then the hard-timeout will kill the task.

    If a hard timeout is triggered, we will mark this worker process as "draining". This will signal
    to the orchistrator that a new worker should be spawned instead of assigning any more work
    to this worker. We will then let the other threads drain out and then kill the worker process
    once all the threads have finished naturally or are hard-terminated.

    We boot up one worker process per core, by default. This process contains:
    - helper ping thread: communicate the health of the worker process
    - a watcher thread: to monitor the execution time of the threads
    - one thread per thread pool, is recycled after each task
        - within each worker thread: a new event loop
        - soft-timeout monitor and worker function both spawned into the event loop

    NOTE: Thread timing appears to only be available in the current thread's process
    parent. We need to use raw OS functions for this since python only provides timing
    for the current thread. If the worker thread is blocking, this isn't helpful.

    """

    def __init__(
        self,
        task_queue: "Queue[TaskDefinition]",
        *,
        pool_size: int,
        tasks_before_recycle: int | None = None,
    ):
        """
        :param tasks_before_recycle: If set, the worker process will stop accepting
            tasks and start to drain the pool after this many tasks have been processed. Note
            that we include timed-out tasks in this count. If this is None, the worker process
            will continue to accept tasks until another termination event occurs.

        """
        super().__init__()

        # Initialized by the parent process
        self.task_queue = task_queue
        self.pool_size = pool_size
        self.tasks_before_recycle = tasks_before_recycle
        self.is_draining_callbacks : list[Callable] = []
        self.process_id = uuid4()

        # Assumes we're instantiating the worker process after we've imported all
        # the modules that we want to use into the global namespace, and therfore
        # into the registry.
        self.action_modules = REGISTRY.get_modules_in_registry()

        # Allows listeners to get alerted when the worker process is draining
        self.is_draining_event = Queue(maxsize=1)

    def start(self):
        # Needs to be spawned in the parent process
        is_draining_monitor = Thread(target=self.monitor_is_draining, daemon=True)
        is_draining_monitor.start()

        super().start()

    def worker_init(self):
        # Usable within the worker process
        self.pool_semaphore = Semaphore(self.pool_size)
        self.is_draining = False
        self.pool_threads_lock = Lock()
        self.pool_threads: dict[UUID, ThreadDefinition] = {}

        # Load back the modules into the new process's registry
        REGISTRY.load_modules(self.action_modules)

    def run(self):
        self.worker_init()

        # ping_thread = Thread(target=self.ping, daemon=True)
        # ping_thread.start()

        watcher_thread = Thread(target=self.watch, daemon=True)
        watcher_thread.start()

        # Only tracked if tasks_before_recycle is set
        handled_tasks = 0

        while not self.is_draining:
            # Get access to a free slot before we try to dequeue a task
            # This keeps the FIFO ordering of the task processing
            self.pool_semaphore.acquire()

            try:
                task = self.task_queue.get(timeout=1)
            except (Empty, Full):
                # Release the semaphore and try again
                self.pool_semaphore.release()
                continue

            # Explicit termination signal
            if task is None:
                break

            LOGGER.debug(f"Received task: {task}")
            self.execute_task(task)

            # If we have exhausted the number of tasks we can process, we
            # should start draining the pool
            if self.tasks_before_recycle is not None:
                handled_tasks += 1
                if handled_tasks >= self.tasks_before_recycle:
                    self.flag_is_draining()

        # If this triggered we must be draining
        # The watch thread will process until this process is safe to kill
        LOGGER.debug("Joining on watcher thread.")
        watcher_thread.join()

    def watch(self):
        initialized_watch = False

        # During a drain, run() will stop executing new tasks
        # In this case we wait for all existing launched threads to reach
        # their successful termination, soft timeout, or hard timeout. We keep
        # moving these out of the "valid" thread pool until this while loop exits
        # gracefully and the process can exit itself.
        while self.is_draining is False or len(self.valid_pool_threads) > 0:
            # TODO: Benchmark overhead of thread_is_timed_out and consider making
            # this sleep parameter larger and/or configurable to minimize the amount
            # of computation we have to do to manage thread lifecycle.
            #
            # We put the sleep at the beginning (after the first run) because this
            # guarantees that we have just validated our while loop definition
            # and there are more threads that need work done.
            # If we put it at the end of the loop we would needlessly sleep after
            # the last thread has been processed.
            if initialized_watch:
                sleep(1)
            initialized_watch = True

            to_delete_ids: set[UUID] = set()

            # Copy values in case they are modified by another thread while we're looping
            for definition in list(self.pool_threads.values()):
                if not definition.thread:
                    # We shouldn't get here
                    LOGGER.warning(
                        f"Cleanup process found {definition.thread_id} without initialized thread."
                    )
                elif definition.thread.is_alive():
                    # We want to potentially trigger this multiple times, even after the process
                    # has timed out once. This lets us escalate from soft to hard timeouts.
                    if timeout_type := self.thread_is_timed_out(definition):
                        if timeout_type in definition.timed_out_causes:
                            # We've already processed this timeout type
                            continue

                        LOGGER.warning(
                            f"Thread {definition.thread_id} has exceeded its {timeout_type} timeout."
                        )
                        definition.timed_out_causes.add(timeout_type)

                        # Special handling for hard timeouts
                        if timeout_type == TimeoutType.HARD:
                            self.trigger_hard_timeout(definition)
                elif not definition.thread.is_alive():
                    LOGGER.warning(
                        f"Cleanup process found {definition.thread_id} crashed without cleaning up thread definitions."
                    )
                    to_delete_ids.add(definition.thread_id)

            for to_delete_id in to_delete_ids:
                self.remove_thread_from_pool(to_delete_id)

    def thread_is_timed_out(self, definition: ThreadDefinition) -> TimeoutType | None:
        """
        Determines if the thread has exceeded its time limits and triggered either
        a soft or hard timeout type. If None is returned, the thread is still within
        its execution limits.

        """
        # This shouldn't happen because parent callers should check for thread validity, but if
        # it does we should just ignore it
        if not definition.thread:
            return None

        wall_elapsed = datetime.now() - definition.started_wall
        cpu_elapsed = filzl_daemons_rs.get_thread_cpu_time(definition.thread.ident)

        # Process hard timeouts first, since if these violate we should take
        # action immediately
        time_priority = {
            TimeoutType.HARD: 0,
            TimeoutType.SOFT: 1,
        }

        for timeout in sorted(
            definition.timeouts, key=lambda x: time_priority[x.timeout_type]
        ):
            if (
                timeout.measurement == TimeoutMeasureType.WALL_TIME
                and wall_elapsed.total_seconds() > timeout.timeout_seconds
                or timeout.measurement == TimeoutMeasureType.CPU_TIME
                and cpu_elapsed > timeout.timeout_seconds
            ):
                return timeout.timeout_type

        return None

    def trigger_hard_timeout(self, thread_definition: ThreadDefinition):
        self.flag_is_draining()

    def execute_task(self, task_definition: TaskDefinition):
        # Stub definition
        thread_definition = ThreadDefinition(
            thread_id=uuid4(),
            thread=None,
            started_wall=datetime.now(),
            timeouts=task_definition.timeouts,
        )

        # We launch each thread pool as a daemon so they will be killed by the OS when we let our
        # process terminate, which is true after the draining has completed
        thread = Thread(
            target=self.task_thread,
            args=(task_definition, thread_definition),
            daemon=True,
        )
        thread_definition.thread = thread

        with self.pool_threads_lock:
            self.pool_threads[thread_definition.thread_id] = thread_definition

        thread.start()

    def task_thread(
        self, task_definition: TaskDefinition, thread_definition: ThreadDefinition
    ):
        LOGGER.info(f"Thread {thread_definition.thread_id} is starting...")
        worker_event_loop = asyncio.new_event_loop()

        async def soft_timeout():
            nonlocal worker_event_loop

            # We won't need to check this value until we hit at least one of time
            # timeout intervals, so we do an initial sleep until the earliest point
            # we need to check for a timeout
            all_timeouts = [
                timeout.timeout_seconds
                for timeout in thread_definition.timeouts
                if timeout.timeout_type == TimeoutType.SOFT
            ]

            if not all_timeouts:
                # User must be running with hard timeouts so we have nothing to do
                return

            min_timeout = min(all_timeouts)
            await asyncio.sleep(min_timeout)

            # After this, we check status every second to see if our watchdog flagged
            # us for a timeout
            while True:
                if thread_definition.timed_out_causes:
                    LOGGER.info("Thread timed out, trying a soft cancel...")
                    # Try to cancel the task
                    task_runner.cancel()
                    worker_event_loop.stop()
                    LOGGER.debug("Asyncio task cancelled, now returning...")
                    return
                await asyncio.sleep(1)

        async def run_task():
            task_fn = REGISTRY.get_action(task_definition.registry_id)
            result = await task_fn(*task_definition.args, **task_definition.kwargs)

            # TODO: Upload the result to the results queue
            # print(result)
            LOGGER.info(f"Process result: {result}")

            LOGGER.debug(f"Thread {thread_definition.thread_id} has finished its task.")
            worker_event_loop.stop()

        task_runner = worker_event_loop.create_task(run_task())
        worker_event_loop.create_task(soft_timeout())
        worker_event_loop.run_forever()

        # Remove this ID from the pool
        self.remove_thread_from_pool(thread_definition.thread_id)

    @property
    def valid_pool_threads(self):
        """
        Returns the pool threads that should count for the overall
        status of the pool (ie. active and not timed out).

        """
        with self.pool_threads_lock:
            return {
                thread_id: thread_definition
                for thread_id, thread_definition in self.pool_threads.items()
                if thread_definition.thread
                and thread_definition.thread.is_alive()
                and not thread_definition.timed_out_causes
            }

    def add_is_draining_callback(self, callback: Callable):
        """
        Notify a client function in the parent process when the pool starts draining.

        """
        self.is_draining_callbacks.append(callback)

    def monitor_is_draining(self):
        while True:
            try:
                self.is_draining_event.get_nowait()
            except Empty:
                continue

            for callback in self.is_draining_callbacks:
                callback(self)

    def flag_is_draining(self):
        if self.is_draining:
            return

        self.is_draining = True
        try:
            self.is_draining_event.put_nowait(True)
        except Full:
            # Shouldn't happen because we should only send one is_draining event per process
            LOGGER.warning("Draining event queue is full, cannot put is_draining event.")
            return

    def remove_thread_from_pool(self, thread_id: UUID):
        with self.pool_threads_lock:
            if thread_id in self.pool_threads:
                del self.pool_threads[thread_id]
                self.pool_semaphore.release()
