import asyncio
from contextlib import asynccontextmanager
import multiprocessing
from abc import ABC, ABCMeta, abstractmethod
from datetime import datetime
from typing import Any, Awaitable, Generic, Type, TypeVar, get_args, get_origin
from uuid import UUID

from filzl.logging import LOGGER
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from traceback import format_exc
from threading import Thread
from sqlalchemy.exc import SQLAlchemyError

from filzl_daemons.db import PostgresBackend
from filzl_daemons.models import LocalModelDefinition
from filzl_daemons.registry import REGISTRY
from filzl_daemons.timeouts import TimeoutDefinition, TimeoutMeasureType, TimeoutType
from filzl_daemons.worker import TaskDefinition, WorkerProcess
from filzl_daemons.actions import ActionExecutionStub
from filzl_daemons.tasks import TaskManager
from filzl_daemons.thread import AlertThread
from sqlalchemy.future import select

T = TypeVar("T", bound=BaseModel)


class WorkflowInstance(Generic[T]):
    def __init__(self, input_payload: T, task_manager: TaskManager):
        self.input_payload = input_payload
        self.task_manager = task_manager

    async def run_action(
        self,
        action: Awaitable[T],
        timeouts: list[TimeoutDefinition] | None = None,
        max_retries: int = 0,
    ) -> T:
        """
        Main entry point for running an action in the workflow. All calls should
        flow through your instance's run_action method.

        This method allows us to inject instance-specific metadata into
        the action.

        """
        # Execute the awaitable. If we receive a promise, we should queue it in
        # the backend
        result = await action

        if isinstance(result, ActionExecutionStub):
            # Queue the action
            wait_future = await self.task_manager.queue_work(
                result
            )
            result = await wait_future

        return result

class WorkflowMeta(ABCMeta):
    def __init__(cls, name, bases, dct):
        super().__init__(name, bases, dct)
        REGISTRY.register_workflow(cls)

        print("REGISTER CLASS", cls.__name__)
        # Attempt to sniff the generic type for input_model
        for base in cls.__orig_bases__:
            print("BASE", base)
            if (
                get_origin(base)
                and get_origin(base).__name__ == "Workflow"
                and get_args(base)
            ):
                # Make sure it's a BaseModel
                if not issubclass(get_args(base)[0], BaseModel):
                    raise Exception(
                        f"Workflow {cls.__name__} must have a BaseModel as its generic type"
                    )
                cls.input_model = get_args(base)[0]
                print("INPUT MODEL", cls.input_model)
                break


class Workflow(ABC, Generic[T], metaclass=WorkflowMeta):
    def __init__(
        self,
        model_definitions: LocalModelDefinition,
        session_maker: async_sessionmaker,
    ):
        self.model_definitions = model_definitions
        self.session_maker = session_maker

    @abstractmethod
    async def run(self, input_payload: WorkflowInstance[T]) -> Any:
        pass

    async def run_handler(
        self,
        instance_id: int,
        raw_input: str,
        task_manager,
    ):
        print("RUN HANDLER TRIGGERED")
        try:
            input_payload = self.input_model.parse_raw(raw_input)
            print("PARSED INPUT", input_payload)

            result = await self.run(WorkflowInstance(input_payload, task_manager))

            async with self.session_maker() as session:
                instance = await session.get(
                    self.model_definitions.DaemonWorkflowInstance,
                    instance_id,
                )
                instance.result_body = result.model_dump_json()
                instance.end_time = datetime.now()
                await session.commit()
        except Exception as e:
            LOGGER.exception(f"Workflow {self.__class__.__name__} failed due to: {e}")

            async with self.session_maker() as session:
                instance = await session.get(
                    self.model_definitions.DaemonWorkflowInstance,
                    instance_id,
                )
                instance.exception = str(e)
                instance.exception_stack = format_exc()
                await session.commit()

    async def queue_task(self, task_input: T):
        print(
            "DB INSTANCE TYPE",
            self.model_definitions.DaemonWorkflowInstance.__tablename__,
        )
        db_instance = self.model_definitions.DaemonWorkflowInstance(
            workflow_name=self.__class__.__name__,
            registry_id=REGISTRY.get_registry_id_for_workflow(self.__class__),
            input_body=task_input.model_dump_json(),
            launch_time=datetime.now(),
        )
        print("DB INSTANCE QUEUED", db_instance)

        async with self.session_maker() as session:
            session.add(db_instance)
            await session.commit()


class DaemonClient:
    """
    Interacts with a remote daemon pool from client code.

    """

    def __init__(
        self,
        model_definitions: LocalModelDefinition,
        engine: AsyncEngine,
    ):
        """
        Workflows only need to be provided if the daemon becomes a runner
        """
        self.model_definitions = model_definitions
        self.engine = engine
        self.session_maker = async_sessionmaker(engine, expire_on_commit=False)

        self.workflows: dict[Type[Workflow], Workflow] = {}

    async def queue_new(self, workflow: Type[Workflow[T]], payload: T):
        """
        Client callers should call this method to queue a new task

        """
        if workflow not in self.workflows:
            self.workflows[workflow] = workflow(
                model_definitions=self.model_definitions,
                session_maker=self.session_maker,
            )
        await self.workflows[workflow].queue_task(payload)


class DaemonRunner:
    """
    Runs the daemon in the current container / machine. Supports multiple workflows
    running in one DaemonRunner.

    """

    def __init__(
        self,
        model_definitions: LocalModelDefinition,
        engine: AsyncEngine,
        workflows: list[Type[Workflow[T]]],
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
        self.model_definitions = model_definitions
        self.engine = engine
        self.session_maker = async_sessionmaker(engine, expire_on_commit=False)
        self.workflows = workflows

        self.postgres_backend = PostgresBackend(engine=self.engine)

        self.max_workers = max_workers or multiprocessing.cpu_count()
        self.threads_per_worker = threads_per_worker

    def run(self, workflows):
        """
        Runs the selected workflows / actions.

        """
        asyncio.run(self.handle_jobs())

    async def handle_jobs(self):
        """
        Main task execution entrypoint. Takes care of:
            - Setting up isolated worker processes, one per CPU
            - Healthcheck those isolated worker processes, replace the ones that have issues
            - Iterate through the instance queue and add the ready workflows to the current
                async loop for execution
            - Iterate through the action queue and assign work to the workers

        """
        # Spawn our worker processes
        worker_processes: dict[UUID, WorkerProcess] = {}
        already_drained: set[UUID] = set()

        # Workers only handle actions, so we set up a queue to route all the collected
        # actions in the format that the workers expect
        worker_queue: multiprocessing.Queue[TaskDefinition] = multiprocessing.Queue(
            maxsize=self.max_workers * self.threads_per_worker
        )
        worker_result_queue: multiprocessing.Queue[
            tuple[int, str]
        ] = multiprocessing.Queue()
        instance_queue = multiprocessing.Queue()

        local_result_queue = asyncio.Queue()

        task_manager = TaskManager(
            local_model_definition=self.model_definitions,
            postgres_backend=self.postgres_backend,
        )

        def start_new_worker():
            # Start a new worker to replace the one that's draining
            process = WorkerProcess(worker_queue, worker_result_queue, pool_size=self.threads_per_worker)
            process.start()

            # Make sure to do after the process is started
            process.add_is_draining_callback(is_draining_callback)

            return process

        def is_draining_callback(worker: WorkerProcess):
            # If we're alerted that the process is draining, we should
            # start a new one. Also handle the case where processes quit
            # without a draining signal.
            if worker.process_id in already_drained:
                return
            already_drained.add(worker.process_id)

            process = start_new_worker()
            worker_processes[process.process_id] = process

        async def health_check():
            while True:
                LOGGER.debug("Running health check")
                # If the process has been terminated without a draining signal,
                # we should start a new one
                for process_id, process in list(worker_processes.items()):
                    # Handle potential terminations of the process for other reasons
                    if not process.is_alive():
                        is_draining_callback(process)
                    del worker_processes[process_id]

                await asyncio.sleep(5)

        # Initial worker process bootstrap for action handlers
        for _ in range(self.max_workers):
            process = start_new_worker()
            worker_processes[process.process_id] = process

        result_handler_thread = AlertThread(
            target=self.consume_action_results,
            args=(worker_result_queue,local_result_queue),
            daemon=True,
        )
        result_handler_thread.start()
        print("Did start result handler thread")

        # Infinitely blocking
        await asyncio.gather(
            # Bulk execute the instance behavior in this main process, for now
            self.queue_instance_work(instance_queue, task_manager),

            # We will consume database actions here and delegate to our other processes
            self.queue_action_work(worker_queue),

            # Consume action results and persist them to the database
            self.consume_actions_results_local(
                local_result_queue,
            ),

            health_check(),

            # Required to wake up our sleeping instance workers
            # when we are done processing an action
            task_manager.delegate_done_actions(),
        )

    async def consume_actions_results_local(
        self,
        local_result_queue,
    ):
        while True:
            print("WILL WAIT TO CONSUME")
            # TODO: WHY DO WE NEED THIS?
            await asyncio.sleep(0.1)
            action_id, result = await local_result_queue.get()
            print("Got local result", result)
            # Save the result to the database
            async with self.session_maker() as session:
                # We need to create a new action result
                action_result_obj = self.model_definitions.DaemonActionResult(
                    action_id=action_id,
                    result_body=result,
                )
                session.add(action_result_obj)
                await session.commit()

                action_obj = await session.get(
                    self.model_definitions.DaemonAction,
                    action_id,
                )
                action_obj.final_result_id = action_result_obj.id
                action_obj.status = "done"
                await session.commit()
                print("DID COMMIT")

    def consume_action_results(
        self,
        result_queue: multiprocessing.Queue,
        local_queue: asyncio.Queue,
    ):
        """
        Small handler function to consume the results of the worker processes
        (in a multiprocessing safe queue) and route them to our database. We use
        this thread as a simple process->asyncio bridge.

        """
        print("Launched consume_action_results thread")
        async def handler():
            while True:
                action_id, result = result_queue.get()
                LOGGER.info(f"Got result from worker: {action_id} {result}")
                await local_queue.put((action_id, result))
                print("ROUTED LOCAL")
        asyncio.run(handler())

    async def queue_instance_work(
        self,
        instance_queue: multiprocessing.Queue,
        task_manager
    ):
        async for notification in self.postgres_backend.iter_ready_objects(
            model=self.model_definitions.DaemonWorkflowInstance,
            queues=[],
        ):
            LOGGER.info(f"Instance queue should handle job: {notification}")

            has_exclusive = await self.get_exclusive_access(
                self.model_definitions.DaemonWorkflowInstance,
                notification.id
            )
            if not has_exclusive:
                print("NO EXCLUSIVE")
                continue

            print("GOT EXCLUSIVE")

            # TODO: Right now we just instantiate a new workflow every time, we should keep
            # this cached in case there is some heavy loading in init
            instance_definition = await self.postgres_backend.get_object_by_id(
                self.model_definitions.DaemonWorkflowInstance, notification.id
            )

            if not instance_definition.id:
                continue

            # Get the workflow class from the workflow name
            workflow_cls = REGISTRY.get_workflow(instance_definition.registry_id)
            workflow = workflow_cls(
                model_definitions=self.model_definitions,
                session_maker=self.session_maker,
            )
            asyncio.create_task(
                workflow.run_handler(
                    instance_id=instance_definition.id,
                    raw_input=instance_definition.input_body,
                    task_manager=task_manager,
                )
            )

    async def queue_action_work(self, worker_queue):
        async for notification in self.postgres_backend.iter_ready_objects(
            model=self.model_definitions.DaemonAction,
            queues=[],
        ):
            LOGGER.info(f"Action queue should handle job: {notification}")

            has_exclusive = await self.get_exclusive_access(
                self.model_definitions.DaemonAction,
                notification.id
            )
            if not has_exclusive:
                print("NO EXCLUSIVE")
                continue

            print("GOT EXCLUSIVE")

            # Get the full object from the database
            action_definition = await self.postgres_backend.get_object_by_id(
                model=self.model_definitions.DaemonAction,
                id=notification.id,
            )

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
            worker_queue.put(task_definition)

    async def get_exclusive_access(self, model, id: int):
        has_exclusive_lock = True

        async with self.session_maker() as session:
            try:
                async with session.begin():
                    # Attempt to lock the specific job by ID with NOWAIT
                    stmt = select(model).where(model.id == id).with_for_update(nowait=True)
                    result = await session.execute(stmt)
                    job = result.scalar_one_or_none()

                    if job:
                        print(f"Job {job.id} locked for processing.")
                        # Process the job here (dummy processing shown as a print statement)
                        print(f"Processing job {job.id}...")

                        # After processing, you might want to update the job's status or mark it as processed
                        job.status = 'processed'  # Assuming the model has a 'status' attribute
                        await session.commit()  # Commit the transaction to save changes
                        has_exclusive_lock = True

            except SQLAlchemyError as e:
                # Handle the case where locking the job fails because it's already locked
                await session.rollback()  # Rollback the transaction if any error occurs
                print(f"Failed to lock job {id}: {e}")

        return has_exclusive_lock
