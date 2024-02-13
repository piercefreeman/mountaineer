import asyncio
import multiprocessing
from abc import ABC, ABCMeta, abstractmethod
from datetime import datetime
from typing import Any, Awaitable, Generic, Type, TypeVar, get_args, get_origin
from uuid import UUID

from filzl.logging import LOGGER
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from filzl_daemons.db import PostgresBackend
from filzl_daemons.instance_worker import InstanceTask, InstanceWorker
from filzl_daemons.models import LocalModelDefinition
from filzl_daemons.registry import REGISTRY
from filzl_daemons.timeouts import TimeoutDefinition, TimeoutMeasureType, TimeoutType
from filzl_daemons.worker import TaskDefinition, WorkerProcess

T = TypeVar("T", bound=BaseModel)


class WorkflowInstance(Generic[T]):
    def __init__(self, input_payload: T):
        self.input_payload = input_payload

    async def run_action(
        self,
        action: Awaitable,
        timeouts: list[TimeoutDefinition],
        max_retries: int,
    ):
        """
        Main entry point for running an action in the workflow. All calls should
        flow through your instance's run_action method.

        This method allows us to inject instance-specific metadata into
        the action.

        """
        pass


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
    ):
        print("RUN HANDLER TRIGGERED")
        try:
            input_payload = self.input_model.parse_raw(raw_input)
            print("PARSED INPUT", input_payload)

            result = await self.run(WorkflowInstance(input_payload))

            async with self.session_maker() as session:
                instance = await session.get(
                    self.model_definitions.DaemonWorkflowInstance,
                    instance_id,
                )
                instance.output_body = result.model_dump_json()
                instance.end_time = datetime.now()
                await session.commit()
        except Exception as e:
            LOGGER.error(f"Workflow {self.__class__.__name__} failed due to: {e}")

            async with self.session_maker() as session:
                instance = await session.get(
                    self.model_definitions.DaemonWorkflowInstance,
                    instance_id,
                )
                instance.error = str(e)
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
        instance_queue = multiprocessing.Queue()

        def start_new_worker():
            # Start a new worker to replace the one that's draining
            process = WorkerProcess(worker_queue, pool_size=self.threads_per_worker)
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

        async def health_check(self, worker_processes: dict[UUID, WorkerProcess]):
            # If the process has been terminated without a draining signal,
            # we should start a new one
            for process_id, process in list(worker_processes.items()):
                # Handle potential terminations of the process for other reasons
                if not process.is_alive():
                    is_draining_callback(process)
                del worker_processes[process_id]

            await asyncio.sleep(5)

        # Initial worker process bootstrap
        # for _ in range(self.max_workers):
        #    process = start_new_worker()
        #    worker_processes[process.process_id] = process

        # handle_workflows_thread = Thread(
        #    target=self.handle_workflows,
        #    args=(instance_queue,),
        #    daemon=True,
        # )
        handle_workflows = InstanceWorker(
            instance_queue,
            self.postgres_backend,
        )
        handle_workflows.start()

        # Infinitely blocking
        await asyncio.gather(
            self.queue_instance_work(instance_queue),
            # queue_action_work(),
            # health_check(),
        )

    async def queue_instance_work(
        self, instance_queue: multiprocessing.Queue
    ):
        async for notification in self.postgres_backend.iter_ready_objects(
            model=self.model_definitions.DaemonWorkflowInstance,
            queues=[],
        ):
            LOGGER.info(f"Instance queue should handle job: {notification}")

            # TODO: Right now we just instantiate a new workflow every time, we should keep
            # this cached in case there is some heavy loading in init
            instance_definition = await self.postgres_backend.get_object_by_id(
                self.model_definitions.DaemonWorkflowInstance, notification.id
            )

            if not instance_definition.id:
                continue

            task_definition = InstanceTask(
                registry_id=instance_definition.registry_id,
                id=instance_definition.id,
                input_body=instance_definition.input_body,
            )
            print("WILL PUT INSTANCE")
            instance_queue.put(task_definition)
            print("DID PUT INSTANCE")

    async def queue_action_work(self):
        async for notification in self.postgres_backend.iter_ready_objects(
            model=self.model_definitions.DaemonAction,
            queues=[],
        ):
            LOGGER.info(f"Action queue should handle job: {notification}")

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
