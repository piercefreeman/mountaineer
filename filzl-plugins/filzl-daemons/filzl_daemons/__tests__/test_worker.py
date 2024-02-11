from multiprocessing import Queue
from filzl_daemons.worker import WorkerProcess, TimeoutMeasureType, TaskDefinition, TimeoutDefinition, TimeoutType
from time import sleep
from filzl_daemons.actions import action, REGISTRY

@action
async def example_action():
    sleep(5)
    # Calculate 100,000 primes
    from tqdm import tqdm
    for i in tqdm(range(500000)):
        prime = True
        for j in range(2, i):
            if i % j == 0:
                prime = False
                break
    sleep(5)

@action
async def example_crash():
    raise ValueError("This is a crash")

def test_isolation():
    task_queue = Queue()
    isolation_process = WorkerProcess(task_queue, pool_size=5)
    isolation_process.start()

    task = TaskDefinition(
        registry_id=REGISTRY.get_registry_id_for_action(example_action),
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
        ]
    )
    task_queue.put(task)

    isolation_process.join()

    print("Done")
