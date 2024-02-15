import asyncio
import sys
from datetime import datetime
from multiprocessing import Queue
from time import time

import pytest
from sqlmodel import select

from filzl_daemons.action_worker import (
    ActionWorkerProcess,
    TaskDefinition,
)
from filzl_daemons.actions import REGISTRY, action
from filzl_daemons.db import PostgresBackend
from filzl_daemons.timeouts import (
    TimeoutDefinition,
    TimeoutMeasureType,
    TimeoutType,
)


@action
async def example_cpu_bound():
    """
    CPU bound action that will take ~5min to complete.
    """
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


def test_soft_timeout(capfd, postgres_backend: PostgresBackend):
    task_queue: Queue[TaskDefinition] = Queue()
    isolation_process = ActionWorkerProcess(
        task_queue,
        postgres_backend,
        pool_size=5,
        # By default we won't recycle the worker after a soft crash, so we
        # cap the amount of tasks that can be executed before recycling.
        tasks_before_recycle=1,
    )

    task = TaskDefinition(
        action_id=1,
        registry_id=REGISTRY.get_registry_id_for_action(example_async_chains),
        input_body="",
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


def test_hard_timeout_and_shutdown(postgres_backend: PostgresBackend):
    """
    Ensure that our hard timeout works on a CPU bound action that won't quit otherwise,
    and that we close the worker process after the hard timeout.

    """
    task_queue: Queue[TaskDefinition] = Queue()
    isolation_process = ActionWorkerProcess(task_queue, postgres_backend, pool_size=5)

    task = TaskDefinition(
        action_id=1,
        registry_id=REGISTRY.get_registry_id_for_action(example_cpu_bound),
        input_body="",
        timeouts=[
            TimeoutDefinition(
                measurement=TimeoutMeasureType.CPU_TIME,
                timeout_type=TimeoutType.SOFT,
                timeout_seconds=1,
            ),
            TimeoutDefinition(
                measurement=TimeoutMeasureType.CPU_TIME,
                timeout_type=TimeoutType.HARD,
                timeout_seconds=3,
            ),
        ],
    )

    start = time()

    isolation_process.start()
    task_queue.put(task)
    isolation_process.join()

    elapsed_time = time() - start

    assert elapsed_time >= 3
    # Can take a bit longer to fully quit and join
    assert elapsed_time < 7


@pytest.mark.asyncio
async def test_ping(postgres_backend: PostgresBackend):
    start_time = datetime.now()

    task_queue: Queue[TaskDefinition] = Queue()
    isolation_process = ActionWorkerProcess(task_queue, postgres_backend, pool_size=5)
    isolation_process.start()

    await asyncio.sleep(1)

    # Look up the ping
    async with postgres_backend.session_maker() as session:
        worker_query = select(postgres_backend.local_models.WorkerStatus).where(
            postgres_backend.local_models.WorkerStatus.internal_process_id
            == isolation_process.process_id
        )
        worker_result = await session.execute(worker_query)
        worker_obj = worker_result.scalars().first()
        assert worker_obj
        assert worker_obj.is_action_worker
        assert worker_obj.last_ping > start_time
        assert worker_obj.launch_time > start_time

    isolation_process.terminate()
    isolation_process.join()


@pytest.mark.asyncio
async def test_handle_exception(postgres_backend: PostgresBackend):
    task_queue: Queue[TaskDefinition] = Queue()
    isolation_process = ActionWorkerProcess(
        task_queue,
        postgres_backend,
        pool_size=5,
        tasks_before_recycle=1,
    )

    task = TaskDefinition(
        action_id=1,
        registry_id=REGISTRY.get_registry_id_for_action(example_crash),
        input_body="",
        timeouts=[],
    )
    task_queue.put(task)

    isolation_process.start()
    isolation_process.join()

    async with postgres_backend.session_maker() as session:
        task_query = select(postgres_backend.local_models.DaemonActionResult).where(
            postgres_backend.local_models.DaemonActionResult.action_id == 1
        )
        task_result = await session.execute(task_query)
        task_obj = task_result.scalars().first()
        assert task_obj
        assert task_obj.exception == "This is a crash"
        assert task_obj.exception_stack
        assert "example_crash" in task_obj.exception_stack
        assert "__tests__/test_action_worker.py" in task_obj.exception_stack
