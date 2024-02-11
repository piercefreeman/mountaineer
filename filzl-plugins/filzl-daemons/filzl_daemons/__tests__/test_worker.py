import asyncio
import sys
from multiprocessing import Queue
from time import sleep, time

from filzl_daemons.actions import REGISTRY, action
from filzl_daemons.worker import (
    TaskDefinition,
    TimeoutDefinition,
    TimeoutMeasureType,
    TimeoutType,
    WorkerProcess,
)


@action
async def example_cpu_bound():
    # Test non-CPU bound actions
    sleep(5)

    # Test CPU bound actions
    # This should take around 5mins to complete if uninterupted
    from tqdm import tqdm

    primes_found = 0
    for i in tqdm(range(1000000)):
        prime = True
        for j in range(2, i):
            if i % j == 0:
                prime = False
                break
        if prime:
            primes_found += 1
    return primes_found


@action
async def example_async_chains():
    sys.stdout.write("START")
    await asyncio.sleep(2)
    sys.stdout.write("MIDDLE")
    await asyncio.sleep(2)
    sys.stdout.write("END")


@action
async def example_crash():
    raise ValueError("This is a crash")


def test_soft_timeout(capfd):
    task_queue = Queue()
    isolation_process = WorkerProcess(
        task_queue,
        pool_size=5,
        # By default we won't recycle the worker after a soft crash, so we
        # cap the amount of tasks that can be executed before recycling.
        tasks_before_recycle=1,
    )

    task = TaskDefinition(
        registry_id=REGISTRY.get_registry_id_for_action(example_async_chains),
        args=[],
        kwargs={},
        timeouts=[
            TimeoutDefinition(
                measurement=TimeoutMeasureType.WALL_TIME,
                timeout_type=TimeoutType.SOFT,
                # The first & second print should be triggered and start the second
                # sleep, but the second sleep should be interrupted by the
                # soft timeout.
                timeout_seconds=3,
            ),
        ],
    )
    task_queue.put(task)

    isolation_process.start()
    isolation_process.join()

    # Assert that the stdout is as expected
    captured = capfd.readouterr()
    assert "START" in captured.out
    assert "MIDDLE" in captured.out
    assert "END" not in captured.out


def test_isolation():
    task_queue = Queue()
    isolation_process = WorkerProcess(task_queue, pool_size=5)

    task = TaskDefinition(
        registry_id=REGISTRY.get_registry_id_for_action(example_cpu_bound),
        args=[],
        kwargs={},
        timeouts=[
            TimeoutDefinition(
                measurement=TimeoutMeasureType.CPU_TIME,
                timeout_type=TimeoutType.SOFT,
                timeout_seconds=5,
            ),
            TimeoutDefinition(
                measurement=TimeoutMeasureType.CPU_TIME,
                timeout_type=TimeoutType.HARD,
                timeout_seconds=8,
            ),
        ],
    )

    start = time()
    isolation_process.start()
    task_queue.put(task)
    isolation_process.join()

    assert time() - start < 10
