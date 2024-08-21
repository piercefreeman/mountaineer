from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from mountaineer.cache import AsyncLoopObjectCache
from mountaineer.database.config import DatabaseConfig, PoolType
from mountaineer.database.session import AsyncSession
from mountaineer.dependencies import CoreDependencies
from mountaineer.logging import LOGGER

# We share the connection pool across the entire process
GLOBAL_ENGINE: AsyncLoopObjectCache[AsyncEngine] = AsyncLoopObjectCache()


async def get_db(
    config: DatabaseConfig = Depends(
        CoreDependencies.get_config_with_type(DatabaseConfig)
    ),
):
    """
    Gets the SQLAlchemy engine registered for your application. Since our
    DatabaseConfig specifies global parameters, by default this engine is
    shared across the whole application.

    If called via dependency injection, which is the most common case,
    we will automatically resolve the config for you. Clients just call
    the main function, which will resolve sub-dependencies.

    ```python
    from sqlalchemy.ext.asyncio import AsyncEngine

    async def render(
        self,
        engine: AsyncEngine = Depends(DatabaseDependencies.get_db)
    ):
        ...
    ```

    """
    if not config.SQLALCHEMY_DATABASE_URI:
        raise RuntimeError(f"No SQLALCHEMY_DATABASE_URI set: {config}")

    current_engine = GLOBAL_ENGINE.get_obj()
    if current_engine is not None:
        return current_engine

    async with GLOBAL_ENGINE.get_lock() as current_engine:
        # Another async task set in the meantime
        if current_engine is not None:
            return current_engine

        # Otherwise create a new engine
        engine = create_async_engine(
            str(config.SQLALCHEMY_DATABASE_URI),
            poolclass=(
                NullPool
                if config.DATABASE_POOL_TYPE == PoolType.NULL
                else AsyncAdaptedQueuePool
            ),
        )
        GLOBAL_ENGINE.set_obj(engine)
        return engine


async def get_db_session(
    engine: AsyncEngine = Depends(get_db),
):
    """
    Gets a new, limited scope async session from the global engine. Anything
    that occurs within this managed scope is wrapped in a transaction, so you
    must manually commit your changes with `await session.commit()` when finished.

    Like `get_db`, the engine will be resolved automatically if you call this
    within a dependency injection context.


    ```python
    from sqlalchemy.ext.asyncio import AsyncSession

    async def render(
        self,
        db_session: AsyncSession = Depends(DatabaseDependencies.get_db_session)
    ):
        ...
    ```

    """
    session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_maker() as session:
        try:
            yield session
        except Exception as e:
            # SQLAlchemy provides rollback support automatically with the async session manager
            LOGGER.exception(
                f"Error in user code, rolling back uncommitted db changes: {e}"
            )
            raise


async def unregister_global_engine():
    """
    Unregisters the global engines used by all async loops.
    """
    for key in list(GLOBAL_ENGINE.loop_caches.keys()):
        engine = GLOBAL_ENGINE.loop_caches[key]
        await engine.dispose()
        del GLOBAL_ENGINE.loop_caches[key]
