from fastapi import Depends
from sqlalchemy import AdaptedQueuePool, NullPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from mountaineer.database.config import DatabaseConfig, PoolType
from mountaineer.dependencies import CoreDependencies
from mountaineer.logging import LOGGER

# We share the connection pool across the entire process
GLOBAL_ENGINE: AsyncEngine | None = None


async def get_db(
    config: DatabaseConfig = Depends(
        CoreDependencies.get_config_with_type(DatabaseConfig)
    ),
):
    global GLOBAL_ENGINE

    if not config.SQLALCHEMY_DATABASE_URI:
        raise RuntimeError("No SQLALCHEMY_DATABASE_URI set")

    if GLOBAL_ENGINE is None:
        GLOBAL_ENGINE = create_async_engine(
            str(config.SQLALCHEMY_DATABASE_URI),
            poolclass=NullPool
            if config.DATABASE_POOL_TYPE == PoolType.NULL
            else AdaptedQueuePool,
        )
    return GLOBAL_ENGINE


async def get_db_session(
    engine: AsyncEngine = Depends(get_db),
):
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        try:
            yield session
        except Exception as e:
            # SQLAlchemy provides rollback support automatically with the async session manager
            LOGGER.exception(
                f"Error in user code, rolling back uncommitted db changes: {e}"
            )
            raise
