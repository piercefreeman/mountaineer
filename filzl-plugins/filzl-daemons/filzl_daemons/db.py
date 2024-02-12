from contextlib import asynccontextmanager
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncEngine
import asyncpg

@asynccontextmanager
async def get_asyncpg_connection_from_engine(engine: AsyncEngine) -> asyncpg.Connection:
    """
    Returns the asyncpg connection that backs the given SQLAlchemy async engine

    Note - This connection is still managed by SQLAlchemy, so you should not close it manually

    """
    async with engine.connect() as conn:
        raw_conn = await conn.get_raw_connection()
        yield raw_conn.driver_connection
