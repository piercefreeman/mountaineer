import asyncio

from filzl_daemons.actions import action
from filzl_daemons.logging import LOGGER
from filzl_daemons.loop import CustomRunLoop

# from filzl_daemons.tasks import TASK_MANAGER


def test_workflow():
    loop = CustomRunLoop()
    asyncio.set_event_loop(loop)

    @action
    async def subjob(i):
        result = 0
        for i in range(i):
            result += i
        return result

    async def run_workflow(i=1):
        results = await asyncio.gather(
            subjob(1),
            subjob(10),
        )
        LOGGER.info("RESULTS", results)

    async def handle_jobs():
        await TASK_MANAGER.handle_jobs()

    asyncio.ensure_future(run_workflow(1))
    asyncio.ensure_future(handle_jobs())
    loop.run_forever()
