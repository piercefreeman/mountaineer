import pytest_asyncio

from mountaineer.database.dependencies.core import unregister_global_engine


@pytest_asyncio.fixture(autouse=True)
async def unregister_globals():
    await unregister_global_engine()
