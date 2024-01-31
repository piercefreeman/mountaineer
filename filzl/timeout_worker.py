from abc import abstractmethod
from multiprocessing import Process, Queue
from queue import Empty, Full
from typing import Callable, Generic, TypeVar

INPUT_TYPE = TypeVar("INPUT_TYPE")
OUTPUT_TYPE = TypeVar("OUTPUT_TYPE")


class ShutdownWorker:
    pass


class TimedWorkerQueue(Generic[INPUT_TYPE, OUTPUT_TYPE]):
    """
    A subprocess that works off of a queue. If it is taking longer than
    the required amount of seconds to process each item, it will respawn.

    """

    def __init__(self):
        self.current_process: Process | None = None
        self.work_queue: Queue[INPUT_TYPE | ShutdownWorker] = Queue(maxsize=1)
        self.result_queue: Queue[OUTPUT_TYPE] = Queue(maxsize=1)

    @staticmethod
    def process_internal(
        target: Callable,
        queue: Queue,
        result_queue: Queue,
    ):
        while True:
            payload = queue.get()
            if isinstance(payload, ShutdownWorker):
                return
            result_queue.put(target(payload))

    @staticmethod
    @abstractmethod
    def run(element: INPUT_TYPE) -> OUTPUT_TYPE:
        pass

    def ensure_valid_worker(self):
        """
        Restart the worker process, if necessary.

        """
        if self.current_process is None or not self.current_process.is_alive():
            # We have to spawn a new process; the current queue might be corrupt so we
            # need to create a new one
            self.work_queue = Queue(maxsize=1)
            self.result_queue = Queue(maxsize=1)

            self.current_process = Process(
                target=self.process_internal,
                args=(self.run, self.work_queue, self.result_queue),
            )
            self.current_process.start()

    def process_data(
        self, new_payload: INPUT_TYPE, hard_timeout: float | int
    ) -> OUTPUT_TYPE:
        """
        Main entrypoint to process a new payload by the worker. If results aren't ready
        by the desired interval, we'll take care of restarting the process and raising
        a TimeoutExpired for callers to handle.

        """
        # Make sure we've started the process, although we typically expect parents
        # to call this before they start sending data
        self.ensure_valid_worker()

        self.work_queue.put(new_payload)

        # Wait a max of self.hard_timeout seconds for the process to get results
        # back from the queue
        try:
            return self.result_queue.get(block=True, timeout=hard_timeout)
        except (Empty, Full):
            # If we've timed out, hard abort the process and start a new one
            if self.current_process is not None and self.current_process.is_alive():
                self.current_process.kill()
                self.current_process = None
            raise TimeoutError("Timed out waiting for worker to process data")

    def shutdown(self):
        """
        Gracefully shutdown the worker process.

        """
        if self.current_process is not None and self.current_process.is_alive():
            self.work_queue.put(ShutdownWorker())
            self.current_process.join()
