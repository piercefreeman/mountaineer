import multiprocessing
from os import environ
from warnings import filterwarnings

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel

from filzl_daemons.__tests__.conf_models import (
    LOCAL_MODEL_DEFINITION,
)
from filzl_daemons.client import DaemonClient
from filzl_daemons.db import PostgresBackend
from filzl_daemons.logging import LOGGER


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    test_database_url = "postgresql+asyncpg://filzl_daemons:mysecretpassword@localhost:5434/filzl_daemons_test_db"
    engine = create_async_engine(test_database_url, echo=False)

    # Test if we can connect to the database, if not throw an early error since
    # the user likely hasn't booted up the test database
    try:
        async with engine.connect() as conn:
            # Optionally, you can perform a simple query to ensure the connection is valid
            await conn.execute(text("SELECT 1"))
    except (DBAPIError, OSError) as e:
        # Handle specific database connection errors or raise a custom exception
        raise RuntimeError(
            "Failed to connect to the test database. Please ensure the database is running and accessible."
        ) from e

    # We do this at the beginning (instead of auto-cleaning at the end) to make sure
    # that interrupted runs aren't polluting our database state for a new run, and to
    # allow us to inspect failed tests after they're run
    LOGGER.info("Cleaning up test tables")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

        # Log the tables that were created
        result = await conn.execute(
            text(
                """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
        """
            )
        )
        tables = "\n".join([f"* {table[0]}" for table in result.fetchall()])
        LOGGER.info(f"Created tables:\n{tables}")

    yield engine


@pytest.fixture
def postgres_backend(db_engine: AsyncEngine):
    return PostgresBackend(
        engine=db_engine,
        local_models=LOCAL_MODEL_DEFINITION,
    )


@pytest.fixture
def daemon_runner_manager():
    with multiprocessing.Manager() as manager:
        yield manager


@pytest.fixture
def daemon_client(postgres_backend: PostgresBackend):
    return DaemonClient(
        backend=postgres_backend,
    )


@pytest.fixture(autouse=True)
def enable_async_debug():
    # Allows for easier debugging of our async code
    environ["PYTHONASYNCIODEBUG"] = "1"
    try:
        yield
    finally:
        del environ["PYTHONASYNCIODEBUG"]


@pytest.fixture(autouse=True)
def silence_socket_warnings():
    filterwarnings(action="ignore", message="unclosed", category=ResourceWarning)
