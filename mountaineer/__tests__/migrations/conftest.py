from contextlib import contextmanager
from warnings import filterwarnings

import pytest
from sqlalchemy import exc as sa_exc
from sqlmodel import SQLModel


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
