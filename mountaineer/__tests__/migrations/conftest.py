from contextlib import asynccontextmanager, contextmanager
from os import environ
from warnings import filterwarnings

import pytest
import pytest_asyncio
from fastapi import Depends
from sqlalchemy import exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlmodel import SQLModel, text

from mountaineer.config import ConfigBase, unregister_config
from mountaineer.database import DatabaseDependencies
from mountaineer.database.config import DatabaseConfig
from mountaineer.database.session import AsyncSession
from mountaineer.dependencies.base import get_function_dependencies
from mountaineer.test_utilities import bootstrap_database


@contextmanager
def clear_registration_metadata():
    """
    Temporarily clear the sqlalchemy metadata

    """
    archived_tables = SQLModel.metadata.tables
    archived_schemas = SQLModel.metadata._schemas
    archived_memos = SQLModel.metadata._fk_memos

    try:
        SQLModel.metadata.clear()
        yield
    finally:
        # Restore
        SQLModel.metadata.tables = archived_tables
        SQLModel.metadata._schemas = archived_schemas
        SQLModel.metadata._fk_memos = archived_memos


@pytest_asyncio.fixture
async def clear_all_database_objects(db_session: AsyncSession):
    """
    Clear all database objects, including those not directly created through
    SQLAlchemy.

    """
    # Step 1: Drop all tables in the public schema
    await db_session.exec(
        text(
            """
        DO $$ DECLARE
            r RECORD;
        BEGIN
            FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
            END LOOP;
        END $$;
    """
        )
    )

    # Step 2: Drop all custom types in the public schema
    await db_session.exec(
        text(
            """
        DO $$ DECLARE
            r RECORD;
        BEGIN
            FOR r IN (SELECT typname FROM pg_type WHERE typtype = 'e' AND typnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')) LOOP
                EXECUTE 'DROP TYPE IF EXISTS ' || quote_ident(r.typname) || ' CASCADE';
            END LOOP;
        END $$;
    """
        )
    )

    await db_session.commit()


@pytest.fixture
def isolated_sqlalchemy(clear_all_database_objects):
    """
    Drops database tables and clears the metadata that is registered
    in-memory, just for this test

    """
    # Avoid also creating the tables for other SQLModels that have been defined
    # in memory (and therefore captured in the same registry)
    with clear_registration_metadata():
        # Overrides the warning that we see when creating multiple ExampleDBModels
        # in one session
        filterwarnings("ignore", category=sa_exc.SAWarning)

        yield


class MigrationAppConfig(ConfigBase, DatabaseConfig):
    pass


@pytest.fixture(autouse=True)
def config():
    """
    Test-time configuration. Set to auto-use the fixture so that the configuration
    is mounted and exposed to the dependency injection framework in all tests.

    """
    unregister_config()
    return MigrationAppConfig(
        POSTGRES_HOST=environ.get("TEST_POSTGRES_HOST", "localhost"),
        POSTGRES_USER=environ.get("TEST_POSTGRES_USER", "mountaineer"),
        POSTGRES_PASSWORD=environ.get("TEST_POSTGRES_PASSWORD", "mysecretpassword"),
        POSTGRES_DB=environ.get("TEST_POSTGRES_DB", "mountaineer_test_db"),
        POSTGRES_PORT=int(environ.get("POSTGRES_PORT", "5438")),
    )


@pytest_asyncio.fixture(scope="function")
async def db_engine(config: MigrationAppConfig):
    @asynccontextmanager
    async def run_bootstrap(
        engine: AsyncEngine = Depends(DatabaseDependencies.get_db),
    ):
        await bootstrap_database(engine)
        yield engine

    async with get_function_dependencies(callable=run_bootstrap) as values:
        async with run_bootstrap(**values) as engine:
            yield engine


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine):
    session_maker = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_maker() as session:
        yield session
