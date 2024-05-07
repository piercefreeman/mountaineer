from sqlalchemy.ext.asyncio import AsyncEngine

from mountaineer import Depends
from mountaineer.database import DatabaseDependencies
from mountaineer.migrations.migrator import Migrator


async def get_migrator(db_engine: AsyncEngine = Depends(DatabaseDependencies.get_db)):
    async with Migrator.new_migrator(db_engine) as engine:
        yield engine
