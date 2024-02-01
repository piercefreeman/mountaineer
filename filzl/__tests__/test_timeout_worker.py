from contextlib import contextmanager
from time import sleep, time

import pytest

from filzl.timeout_worker import TimedWorkerQueue


@contextmanager
def require_time(under_threshold: float):
    start = time()
    yield
    assert time() - start < under_threshold, "Processing time exceeded threshold"


class ExampleWaitWorker(TimedWorkerQueue[float, str]):
    @staticmethod
    def run(element: float) -> str:
        # We treat the element as our desired sleep interval
        sleep(element)
        return str(element)


def test_timed_worker_queue():
    # Start the worker out-of-band so any process bootup time doesn't
    # affect the test
    example = ExampleWaitWorker()
    example.ensure_valid_worker()

    # Work for 1s, timeout to set to 5. Should return the result.
    # We'll also check that the worker is still alive
    with require_time(0.5):
        assert example.process_data(0.1, hard_timeout=5) == "0.1"
        assert example.current_process
        assert example.current_process.is_alive()

    # Work for 5s, timeout to set to 1. Should raise a TimeoutError
    # We'll also check that the worker has been killed
    with require_time(0.5):
        with pytest.raises(TimeoutError):
            example.process_data(5, hard_timeout=0.2)

    assert not example.current_process
