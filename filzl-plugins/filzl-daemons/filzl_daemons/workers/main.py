# Support generic Queue[Obj] syntax
from __future__ import annotations

import asyncio
import multiprocessing
from datetime import datetime, timedelta, timezone
from itertools import chain
from multiprocessing.managers import SyncManager
from typing import Type, TypeVar
from uuid import UUID

from filzl.logging import LOGGER
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select

from filzl_daemons.db import PostgresBackend
from filzl_daemons.io import AsyncMultiprocessingQueue, safe_task
from filzl_daemons.models import QueableStatus
from filzl_daemons.tasks import TaskManager
from filzl_daemons.timeouts import TimeoutDefinition, TimeoutMeasureType, TimeoutType
from filzl_daemons.workers.action import ActionWorkerProcess, TaskDefinition
from filzl_daemons.workers.instance import InstanceTaskDefinition, InstanceWorkerProcess
from filzl_daemons.workflow import Workflow

T = TypeVar("T", bound=BaseModel)


class DaemonRunner:
    """
    Runs the daemon in the current container / machine. Supports multiple workflows
    running in one DaemonRunner.

    """

    def __init__(
        self,
        backend: PostgresBackend,
        workflows: list[Type[Workflow[T]]],
        max_workers: int | None = None,
        threads_per_worker: int = 1,
        max_instance_workers: int = 1,
        max_instances_per_worker: int = 1000,
        update_scheduled_refresh: int = 30,
        update_timed_out_workers_refresh: int = 30,
    ):
        """
        :param max_workers: If None, we'll use the number of CPUs on the machine
        :param threads_per_worker: The number of threads to use per worker. If you have
            heavily CPU-bound tasks, keeping the default of 1 task per process is probably
            good. Otherwise in the case of more I/O bound tasks, you might want to increase
            this number.
        :param update_scheduled_refresh: Seconds between bringing the scheduled task queue
            into the main queue.
        :param update_timed_out_workers_refresh: Seconds between checking for timed out
            workers and requeuing their items.

        """
        self.backend = backend
        self.workflows = workflows

        self.max_workers = max_workers or multiprocessing.cpu_count()
        self.threads_per_worker = threads_per_worker
        self.max_instance_workers = max_instance_workers
        self.max_instances_per_worker = max_instances_per_worker

        self.update_scheduled_refresh = update_scheduled_refresh
        self.update_timed_out_workers_refresh = update_timed_out_workers_refresh

    def run(self, workflows):
        """
        Runs the selected workflows / actions.

        """
        with multiprocessing.Manager() as manager:
            asyncio.run(self.handle_jobs(manager))

    async def handle_jobs(self, multiprocessing_manager: SyncManager):
        """
        Main task execution entrypoint. Takes care of:
            - Setting up isolated worker processes, one per CPU
            - Healthcheck those isolated worker processes, replace the ones that have issues
            - Iterate through the instance queue and add the ready workflows to the current
                async loop for execution
            - Iterate through the action queue and assign work to the workers

        """
        # Spawn our worker processes
        worker_processes: dict[UUID, ActionWorkerProcess] = {}
        instance_worker_processes: dict[UUID, InstanceWorkerProcess] = {}
        already_drained: set[UUID] = set()

        # Workers only handle actions, so we set up a queue to route all the collected
        # actions in the format that the workers expect
        worker_queue: multiprocessing.Queue[TaskDefinition] = multiprocessing.Queue(
            maxsize=self.max_workers * self.threads_per_worker
        )
        instance_queue: AsyncMultiprocessingQueue[
            InstanceTaskDefinition
        ] = AsyncMultiprocessingQueue(
            maxsize=self.max_instance_workers * self.max_instances_per_worker
        )

        task_manager = TaskManager(self.backend, manager=multiprocessing_manager)

        async def start_new_worker():
            # Start a new worker to replace the one that's draining
            process = ActionWorkerProcess(
                worker_queue, self.backend, pool_size=self.threads_per_worker
            )
            await process.start()

            # Make sure to do after the process is started
            process.add_is_draining_callback(is_draining_callback)

            worker_processes[process.process_id] = process

            return process

        async def start_new_instance_worker():
            process = InstanceWorkerProcess(
                instance_queue,
                self.backend,
                pool_size=self.max_instances_per_worker,
                task_manager=task_manager,
            )
            task_manager.worker_register(process.process_id)

            await process.start()
            instance_worker_processes[process.process_id] = process

            return process

        async def is_draining_callback(worker: ActionWorkerProcess):
            # If we're alerted that the process is draining, we should
            # start a new one. Also handle the case where processes quit
            # without a draining signal.
            if worker.process_id in already_drained:
                return
            already_drained.add(worker.process_id)

            await start_new_worker()

        async def health_check():
            while True:
                LOGGER.debug("Running health check")
                # If the process has been terminated without a draining signal,
                # we should start a new one
                for process_id, worker_process in list(worker_processes.items()):
                    # Handle potential terminations of the process for other reasons
                    if not worker_process.is_alive():
                        await is_draining_callback(worker_process)
                        del worker_processes[process_id]
                for process_id, instance_process in list(
                    instance_worker_processes.items()
                ):
                    if not instance_process.is_alive():
                        await start_new_instance_worker()
                        del instance_worker_processes[process_id]

                await asyncio.sleep(5)

        # Initial worker process bootstrap for action handlers
        for _ in range(self.max_workers):
            process = await start_new_worker()
            LOGGER.debug(f"Spawned: {process.process_id}")

        for _ in range(self.max_instance_workers):
            process = await start_new_instance_worker()
            LOGGER.debug(f"Spawned: {process.process_id}")

        # Infinitely blocking
        try:
            await asyncio.gather(
                # Bulk execute the instance behavior in this main process, for now
                safe_task(self.queue_instance_work)(instance_queue),
                # We will consume database actions here and delegate to our other processes
                safe_task(self.queue_action_work)(worker_queue),
                # Update the DB-level actions that are now ready to be re-queued
                safe_task(self.update_scheduled_actions)(),
                # Update the DB-level actions/instance values if their workers have timed out
                # Workers themselves will handle the requeue of the actions if they time out within
                # the active runloop
                safe_task(self.update_timed_out_workers)(),
                # Required to wake up our sleeping instance workers
                # when we are done processing an action
                safe_task(task_manager.main_delegate_done_actions)(),
                # Determine the health of our worker processes
                safe_task(health_check)(),
            )
        except asyncio.CancelledError:
            LOGGER.debug(
                f"DaemonRunner was cancelled, cleaning up {len(worker_processes)} worker processes"
            )
            for process in chain(
                worker_processes.values(), instance_worker_processes.values()
            ):
                process.terminate()
            for process in chain(
                worker_processes.values(), instance_worker_processes.values()
            ):
                process.join()
            LOGGER.debug("Worker processes cleaned up")

        LOGGER.debug("DaemonRunner finished")

    async def update_scheduled_actions(self):
        """
        Determine the actions that have been scheduled in the future and are now ready
        to be executed by the action workers.

        """
        while True:
            async with self.backend.session_maker() as session:
                result = await session.execute(
                    text(
                        f"UPDATE {self.backend.local_models.DaemonAction.__tablename__} SET status = :queued_status WHERE status = :scheduled_status AND schedule_after < now()"
                    ),
                    {
                        "queued_status": QueableStatus.QUEUED,
                        "scheduled_status": QueableStatus.SCHEDULED,
                    },
                )
                await session.commit()
                affected_rows = result.rowcount
                LOGGER.debug(f"Updated {affected_rows} scheduled rows")
            await asyncio.sleep(self.update_scheduled_refresh)

    async def update_timed_out_workers(self, worker_timeouts=5 * 60):
        """
        Determine the workers that have timed out and re-queue their actions
        and instances.

        """
        while True:
            await self._update_timed_out_workers_single(worker_timeouts)
            await asyncio.sleep(self.update_timed_out_workers_refresh)

    async def _update_timed_out_workers_single(self, worker_timeouts: int):
        async with self.backend.session_maker() as session:
            # Get all the workers that have timed out and haven't yet been cleaned up
            # We recognize that this can introduce a race condition, but because the actions here are idempotent
            # we can execute the SQL updates multiple times
            current_time = datetime.now(timezone.utc)
            timeout_threshold = current_time - timedelta(seconds=worker_timeouts)

            timed_out_workers_query = text(
                f"""
                SELECT id FROM {self.backend.local_models.WorkerStatus.__tablename__}
                WHERE last_ping < :timeout_threshold AND cleaned_up = FALSE
            """
            )
            timed_out_workers_result = await session.execute(
                timed_out_workers_query, {"timeout_threshold": timeout_threshold}
            )
            timed_out_worker_ids = [row[0] for row in timed_out_workers_result]

            if not timed_out_worker_ids:
                return

            # Right now we requeue action failures immediately if they happened because of a disconnected
            # worker, versus a worker that has timed out.
            result = await session.execute(
                text(
                    f"UPDATE {self.backend.local_models.DaemonAction.__tablename__} SET status = :new_status WHERE status = :old_status AND assigned_worker_status_id = ANY(:timed_out_worker_ids)"
                ),
                {
                    "new_status": QueableStatus.QUEUED,
                    "old_status": QueableStatus.IN_PROGRESS,
                    "timed_out_worker_ids": timed_out_worker_ids,
                },
            )
            await session.commit()
            affected_rows = result.rowcount
            LOGGER.debug(
                f"update_timed_out_workers: Updated {affected_rows} action rows"
            )

            # Run the same logic for the instance table
            result = await session.execute(
                text(
                    f"UPDATE {self.backend.local_models.DaemonWorkflowInstance.__tablename__} SET status = :new_status WHERE status = :old_status AND assigned_worker_status_id = ANY(:timed_out_worker_ids)"
                ),
                {
                    "new_status": QueableStatus.QUEUED,
                    "old_status": QueableStatus.IN_PROGRESS,
                    "timed_out_worker_ids": timed_out_worker_ids,
                },
            )
            affected_rows = result.rowcount
            LOGGER.debug(
                f"update_timed_out_workers: Updated {affected_rows} instance rows"
            )

            # Mark the workers as cleaned up
            cleanup_workers_query = text(
                f"""
                UPDATE {self.backend.local_models.WorkerStatus.__tablename__}
                SET cleaned_up = TRUE
                WHERE id = ANY(:timed_out_worker_ids)
            """
            )
            await session.execute(
                cleanup_workers_query, {"timed_out_worker_ids": timed_out_worker_ids}
            )

            await session.commit()

    async def queue_instance_work(
        self, instance_queue: AsyncMultiprocessingQueue[InstanceTaskDefinition]
    ):
        async for notification in self.backend.iter_ready_objects(
            model=self.backend.local_models.DaemonWorkflowInstance,
            queues=[],
        ):
            LOGGER.info(f"Instance queue should handle job: {notification}")

            has_exclusive = await self.get_exclusive_access(
                self.backend.local_models.DaemonWorkflowInstance, notification.id
            )
            if not has_exclusive:
                continue

            async with self.backend.get_object_by_id(
                self.backend.local_models.DaemonWorkflowInstance, notification.id
            ) as (instance_definition, _):
                pass

            if not instance_definition.id:
                continue

            # Queue up this instance for processing
            task = InstanceTaskDefinition(
                instance_id=instance_definition.id,
                registry_id=instance_definition.registry_id,
                queue_name=instance_definition.workflow_name,
                raw_input=instance_definition.input_body,
            )
            LOGGER.info(f"Queueing instance task: {task} {instance_definition}")

            await instance_queue.async_put(task)

    async def queue_action_work(
        self, worker_queue: multiprocessing.Queue[TaskDefinition]
    ):
        """
        Listen to database changes for actions that are now ready to be executed and place
        them into the multiprocess queue for the system wide workers.

        """
        async for notification in self.backend.iter_ready_objects(
            model=self.backend.local_models.DaemonAction,
            queues=[],
        ):
            LOGGER.info(f"Action queue should handle job: {notification}")

            has_exclusive = await self.get_exclusive_access(
                self.backend.local_models.DaemonAction, notification.id
            )
            if not has_exclusive:
                continue

            # Get the full object from the database
            async with self.backend.get_object_by_id(
                model=self.backend.local_models.DaemonAction,
                id=notification.id,
            ) as (action_definition, _):
                pass

            field_to_timeout = {
                "wall_soft_timeout": (TimeoutMeasureType.WALL_TIME, TimeoutType.SOFT),
                "wall_hard_timeout": (TimeoutMeasureType.WALL_TIME, TimeoutType.HARD),
                "cpu_soft_timeout": (TimeoutMeasureType.CPU_TIME, TimeoutType.SOFT),
                "cpu_hard_timeout": (TimeoutMeasureType.CPU_TIME, TimeoutType.HARD),
            }

            if not action_definition.id:
                LOGGER.error(
                    f"Action definition {action_definition} has no ID. Skipping."
                )
                continue

            task_definition = TaskDefinition(
                action_id=action_definition.id,
                registry_id=action_definition.registry_id,
                input_body=action_definition.input_body,
                timeouts=[
                    TimeoutDefinition(
                        measurement=measure,
                        timeout_type=timeout_type,
                        timeout_seconds=getattr(action_definition, timeout_key),
                    )
                    for timeout_key, (measure, timeout_type) in field_to_timeout.items()
                    if getattr(action_definition, timeout_key) is not None
                ],
            )
            LOGGER.info(f"Will queue: {task_definition} {action_definition}")

            worker_queue.put(task_definition)

    async def get_exclusive_access(self, model, id: int):
        has_exclusive_lock = True

        async with self.backend.session_maker() as session:
            try:
                async with session.begin():
                    # Attempt to lock the specific job by ID with NOWAIT
                    stmt = (
                        select(model).where(model.id == id).with_for_update(nowait=True)
                    )
                    result = await session.execute(stmt)
                    job = result.scalar_one_or_none()

                    if job:
                        job.status = QueableStatus.IN_PROGRESS
                        await session.commit()
                        has_exclusive_lock = True

            except SQLAlchemyError as e:
                # Handle the case where locking the job fails because it's already locked
                await session.rollback()
                LOGGER.debug(f"Failed to lock job {id}: {e}")

        return has_exclusive_lock
