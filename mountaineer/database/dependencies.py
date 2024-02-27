from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from mountaineer.database.config import DatabaseConfig
from mountaineer.dependencies import CoreDependencies, DependenciesBase


def get_db(
    config: DatabaseConfig = Depends(
        CoreDependencies.get_config_with_type(DatabaseConfig)
    ),
):
    if not config.SQLALCHEMY_DATABASE_URI:
        raise RuntimeError("No SQLALCHEMY_DATABASE_URI set")

    return create_async_engine(str(config.SQLALCHEMY_DATABASE_URI))


async def get_db_session(
    engine: AsyncEngine = Depends(get_db),
):
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session


class DatabaseDependencies(DependenciesBase):
    """
    Dependencies for use in API endpoint routes.

    """

    get_db = get_db
    get_db_session = get_db_session
