from typing import Any

import pytest
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from mountaineer.database.config import DatabaseConfig, PoolType
from mountaineer.database.dependencies.core import get_db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pool_type, pool_class",
    [
        (PoolType.NULL, NullPool),
        (PoolType.FIXED_PROCESS, AsyncAdaptedQueuePool),
    ],
)
async def test_get_db_null_pool(
    pool_type: PoolType,
    pool_class: Any,
):
    config = DatabaseConfig(
        POSTGRES_HOST="localhost",
        POSTGRES_USER="mock_user",
        POSTGRES_PASSWORD="mock_password",
        POSTGRES_DB="mock_db",
        DATABASE_POOL_TYPE=pool_type,
    )

    db_engine = await get_db(config=config)
    assert isinstance(db_engine.pool, pool_class)
