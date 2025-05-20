from os import environ

import pytest
import pytest_asyncio
import asyncpg

from mountaineer.config import unregister_config
from iceaxe import DBConnection
from iceaxe.mountaineer import DatabaseConfig

from {{project_name}}.config import AppConfig


@pytest.fixture(autouse=True)
def config():
    """
    Test-time configuration. Set to auto-use the fixture so that the configuration
    is mounted and exposed to the dependency injection framework in all tests.

    """
    unregister_config()
    common_db = DatabaseConfig(
        POSTGRES_HOST=environ.get("TEST_POSTGRES_HOST", "localhost"),
        POSTGRES_USER=environ.get("TEST_POSTGRES_USER", "mountaineer_plugins_web"),
        POSTGRES_PASSWORD=environ.get("TEST_POSTGRES_PASSWORD", "mysecretpassword"),
        POSTGRES_DB=environ.get("TEST_POSTGRES_DB", "mountaineer_plugins_web_test_db"),
        POSTGRES_PORT=int(environ.get("POSTGRES_PORT", "5438")),
    )
    return AppConfig(
        **common_db.model_dump(),
        # Ignore the actual defaults
        _env_file=".env.test",  # type: ignore
    )


@pytest_asyncio.fixture
async def db_connection(config: AppConfig):
    db_connection = DBConnection(
        await asyncpg.connect(
            host=config.POSTGRES_HOST,
            port=config.POSTGRES_PORT,
            user=config.POSTGRES_USER,
            password=config.POSTGRES_PASSWORD,
            database=config.POSTGRES_DB,
        )
    )

    # Step 1: Drop all tables in the public schema
    await db_connection.conn.execute(
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

    # Step 2: Drop all custom types in the public schema
    await db_connection.conn.execute(
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

    from iceaxe.schemas.cli import create_all

    await create_all(db_connection)

    return db_connection
