from tempfile import TemporaryDirectory
import pytest
from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine, Session
from filzl_daemons import models
from pathlib import Path
from filzl_daemons.workflow import Daemon
from filzl_daemons.__tests__.conf_models import DaemonWorkflowInstance, WorkerStatus, DaemonAction, DaemonActionResult, LOCAL_MODEL_DEFINITION
from sqlalchemy.ext.asyncio import create_async_engine
import pytest_asyncio

@pytest_asyncio.fixture(scope="function")
async def db_engine():
    test_database_url = f"postgresql+asyncpg://filzl_daemons:mysecretpassword@localhost:5434/filzl_daemons_test_db"
    engine = create_async_engine(test_database_url, echo=False)
    print("Creating engine", engine)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)

@pytest.fixture
def daemon_client(db_engine: Engine):
    yield Daemon(
        model_definitions=LOCAL_MODEL_DEFINITION,
        engine=db_engine,
    )
