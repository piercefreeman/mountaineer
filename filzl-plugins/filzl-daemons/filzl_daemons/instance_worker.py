import asyncio
import multiprocessing
from threading import Thread

from pydantic import BaseModel

from filzl_daemons.db import PostgresBackend
from filzl_daemons.loop import CustomRunLoop
from filzl_daemons.registry import REGISTRY
from filzl_daemons.tasks import TaskManager


class InstanceTask(BaseModel):
    registry_id: str
    id: int
    input_body: str


class InstanceWorker(multiprocessing.Process):
    def __init__(
        self,
        instance_queue: multiprocessing.Queue,
        # engine: AsyncEngine,
        backend: PostgresBackend,
    ):
        super().__init__()
        self.instance_queue = instance_queue
        self.backend = backend
        # self.local_model_definition = model_definitions
        # self.session_maker = session_maker
        self.action_modules = REGISTRY.get_modules_in_registry()

    def run(self):
        # Load back the modules into the new process's registry
        REGISTRY.load_modules(self.action_modules)

        print("BOOTING UP INSTANCE QUEUE LOOP")
        instance_loop = CustomRunLoop(
            task_manager=TaskManager(
                postgres_backend=self.backend,
            )
        )
        # instance_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(instance_loop)
        print("SET INSTANCE LOOP", instance_loop)

        def poll_new_instances():
            while True:
                print("POLLING FOR NEW INSTANCES")
                # WHY DO WE NEED THIS?
                # await asyncio.sleep(0.1)
                print("GOT HERE")
                instance_definition = self.instance_queue.get()
                print("GOT INSTANCE", instance_definition)
                workflow_cls = REGISTRY.get_workflow(instance_definition.registry_id)
                print("WORKER CLS", workflow_cls)
                workflow = workflow_cls(
                    model_definitions=None,
                    session_maker=None,
                )

                # Add the workflow to the current event loop
                task = instance_loop.create_task(
                    workflow.run_handler(
                        instance_id=instance_definition.id,
                        raw_input=instance_definition.input_body,
                    )
                )
                print("CREATED EVENT LOOP TASK FOR INSTANCE", task)

        # Place in a separate thread since the queue get call blocks
        poll_thread = Thread(target=poll_new_instances)
        poll_thread.start()

        instance_loop.run_forever()
        print("DID QUEUE INSTANCE LOOP")
