import asyncio
import sys
from datetime import datetime
from multiprocessing import Queue
from time import time

import pytest
import pytest_asyncio
from sqlmodel import select

from filzl_daemons.__tests__.conf_models import (
    DaemonAction,
    DaemonActionResult,
    WorkerStatus,
)
from filzl_daemons.actions import REGISTRY, action
from filzl_daemons.db import PostgresBackend
from filzl_daemons.models import QueableStatus
from filzl_daemons.timeouts import (
    TimeoutDefinition,
    TimeoutMeasureType,
    TimeoutType,
)
from filzl_daemons.workers.action import (
    ActionWorkerProcess,
    TaskDefinition,
)


@action
async def example_cpu_bound() -> None:
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


@action
async def example_async_chains() -> None:
    sys.stdout.write("START")
    await asyncio.sleep(2)
    sys.stdout.write("MIDDLE")
    await asyncio.sleep(3)
    sys.stdout.write("END")


@action
async def example_crash() -> None:
    raise ValueError("This is a crash")


@pytest_asyncio.fixture
async def stub_db_action(postgres_backend: PostgresBackend):
    async with postgres_backend.session_maker() as session:
        action = DaemonAction(
            id=1,
            workflow_name="test_workflow",
            instance_id=1,
            state="",
            registry_id="",
            input_body="",
            retry_backoff_seconds=0,
            retry_backoff_factor=0,
            retry_jitter=0,
        )
        session.add(action)
        await session.commit()
    yield action


@pytest.mark.asyncio
async def test_assign_worker_id(
    postgres_backend: PostgresBackend, stub_db_action: DaemonAction
):
    task_queue: Queue[TaskDefinition] = Queue()
    isolation_process = ActionWorkerProcess(task_queue, postgres_backend, pool_size=5)

    # The worker id generation is kicked off by the start method, so we actually
    # have to start the process
    await isolation_process.start()

    assert isolation_process.worker_id is not None

    isolation_process.terminate()
    isolation_process.join()


@pytest.mark.asyncio
async def test_soft_timeout(
    capfd, postgres_backend: PostgresBackend, stub_db_action: DaemonAction
):
    task_queue: Queue[TaskDefinition] = Queue()
    task_start = datetime.now()
    isolation_process = ActionWorkerProcess(
        task_queue,
        postgres_backend,
        pool_size=5,
        # By default we won't recycle the worker after a soft crash, so we
        # cap the amount of tasks that can be executed before recycling.
        tasks_before_recycle=1,
    )

    assert stub_db_action.id

    task = TaskDefinition(
        action_id=stub_db_action.id,
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

    await isolation_process.start()
    isolation_process.join()

    # Assert that the stdout is as expected
    captured = capfd.readouterr()
    assert "START" in captured.out
    assert "MIDDLE" in captured.out
    assert "END" not in captured.out

    # Ensure that the db action object was updated with the correct state
    async with postgres_backend.get_object_by_id(DaemonAction, 1) as (
        updated_action,
        _,
    ):
        pass
    assert updated_action.status == QueableStatus.SCHEDULED
    assert updated_action.schedule_after
    assert updated_action.final_result_id
    assert updated_action.schedule_after > task_start
    assert updated_action.assigned_worker_status_id == isolation_process.worker_id

    async with postgres_backend.get_object_by_id(
        DaemonActionResult, updated_action.final_result_id
    ) as (action_result, _):
        pass
    assert action_result.result_body is None
    assert action_result.exception == "Task soft-timed out."


@pytest.mark.asyncio
async def test_hard_timeout_and_shutdown(
    postgres_backend: PostgresBackend, stub_db_action: DaemonAction
):
    """
    Ensure that our hard timeout works on a CPU bound action that won't quit otherwise,
    and that we close the worker process after the hard timeout.

    """
    task_start = datetime.now()
    task_queue: Queue[TaskDefinition] = Queue()
    isolation_process = ActionWorkerProcess(task_queue, postgres_backend, pool_size=5)

    assert stub_db_action.id

    task = TaskDefinition(
        action_id=stub_db_action.id,
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

    await isolation_process.start()
    task_queue.put(task)
    isolation_process.join()

    elapsed_time = time() - start

    assert elapsed_time >= 3
    # Can take a bit longer to fully quit and join
    assert elapsed_time < 7

    # Ensure that the db action object was updated with the correct state
    async with postgres_backend.get_object_by_id(DaemonAction, 1) as (
        updated_action,
        _,
    ):
        pass
    assert updated_action.status == QueableStatus.SCHEDULED
    assert updated_action.schedule_after
    assert updated_action.final_result_id
    assert updated_action.schedule_after > task_start
    assert updated_action.assigned_worker_status_id == isolation_process.worker_id

    async with postgres_backend.get_object_by_id(
        DaemonActionResult, updated_action.final_result_id
    ) as (action_result, _):
        pass
    assert action_result.result_body is None
    assert action_result.exception == "Task hard-timed out."


@pytest.mark.asyncio
async def test_ping(postgres_backend: PostgresBackend):
    start_time = datetime.now()

    task_queue: Queue[TaskDefinition] = Queue()
    isolation_process = ActionWorkerProcess(task_queue, postgres_backend, pool_size=5)
    await isolation_process.start()

    await asyncio.sleep(1)

    # Look up the ping
    async with postgres_backend.session_maker() as session:
        worker_query = select(WorkerStatus).where(
            WorkerStatus.internal_process_id == isolation_process.process_id
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
async def test_handle_exception(
    postgres_backend: PostgresBackend, stub_db_action: DaemonAction
):
    task_queue: Queue[TaskDefinition] = Queue()
    isolation_process = ActionWorkerProcess(
        task_queue,
        postgres_backend,
        pool_size=5,
        tasks_before_recycle=1,
    )

    assert stub_db_action.id

    task = TaskDefinition(
        action_id=stub_db_action.id,
        registry_id=REGISTRY.get_registry_id_for_action(example_crash),
        input_body="",
        timeouts=[],
    )
    task_queue.put(task)

    await isolation_process.start()
    isolation_process.join()

    async with postgres_backend.session_maker() as session:
        task_query = select(DaemonActionResult).where(DaemonActionResult.action_id == 1)
        task_result = await session.execute(task_query)
        task_obj = task_result.scalars().first()

        assert task_obj
        assert task_obj.exception == "This is a crash"
        assert task_obj.exception_stack
        assert "example_crash" in task_obj.exception_stack
        assert (
            __name__.lstrip("filzl_daemons.").replace(".", "/")
            in task_obj.exception_stack
        )
