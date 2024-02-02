import ctypes
from abc import abstractmethod
from inspect import isclass
from queue import Empty, Full, Queue
from threading import Thread
from typing import Callable, Generic, TypeVar

from filzl.logging import LOGGER

INPUT_TYPE = TypeVar("INPUT_TYPE")
OUTPUT_TYPE = TypeVar("OUTPUT_TYPE")


class ShutdownWorker:
    pass


def _async_raise(tid, exctype):
    """
    Raises an exception to the given thread
    https://stackoverflow.com/questions/323972/is-there-any-way-to-kill-a-thread
    """
    """Raises an exception in the threads with id tid"""
    if not isclass(exctype):
        raise TypeError("Only types can be raised (not instances)")
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(tid), ctypes.py_object(exctype)
    )
    if res == 0:
        raise ValueError("invalid thread id")
    elif res != 1:
        # "if it returns a number greater than one, you're in trouble,
        # and you should call it again with exc=NULL to revert the effect"
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), None)
        raise SystemError("PyThreadState_SetAsyncExc failed")


class TimedWorkerQueue(Generic[INPUT_TYPE, OUTPUT_TYPE]):
    """
    A thread that works off of a queue. If it is taking longer than
    the required amount of seconds to process each item, it will respawn.

    Originally this was implemented as a separate process, but we benchmarked
    around a ~0.3s overhead for each main process->subprocess->main process queue
    transfer - even when the actual payload size is trivial (0 bytes). We instead
    opt for a thread and manually implement thread hard-stopping behavior.

    """

    def __init__(self):
        self.current_process: Thread | None = None
        self.work_queue: Queue[INPUT_TYPE | ShutdownWorker] = Queue(maxsize=1)
        self.result_queue: Queue[OUTPUT_TYPE] = Queue(maxsize=1)

    @staticmethod
    def process_internal(
        target: Callable,
        queue: Queue,
        result_queue: Queue,
    ):
        while True:
            try:
                payload = queue.get()
            except KeyboardInterrupt:
                LOGGER.debug("TimeoutWorker process received interrupt, shutting down")
                return
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

            self.current_process = Thread(
                target=self.process_internal,
                args=(self.run, self.work_queue, self.result_queue),
                daemon=True,
            )
            self.current_process.start()

    def process_data(
        self, new_payload: INPUT_TYPE, *, hard_timeout: float | int
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
                _async_raise(self.current_process.ident, TimeoutError)
                self.current_process = None
            raise TimeoutError("Timed out waiting for worker to process data")

    def shutdown(self):
        """
        Gracefully shutdown the worker process.

        """
        if self.current_process is not None and self.current_process.is_alive():
            self.work_queue.put(ShutdownWorker())
            self.current_process.join()
