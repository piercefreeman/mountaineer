from contextlib import asynccontextmanager
from typing import cast

from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlmodel import text

from mountaineer.migrations.actions import DatabaseActions


class NoCommitAsyncSession(AsyncSession):
    """
    To be safe in case of an error and rollback, migrations must be run in an isolated
    transaction and shouldn't be committed. This class is a simple wrapper around
    `AsyncSession` that will prevent commits.

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.okay_to_commit = False

    async def commit(self):
        if not self.okay_to_commit:
            raise InvalidRequestError("Commits are disabled for this session.")
        return await super().commit()


class Migrator:
    """
    Main interface for client migrations. Mountaineer provides a simple shim on top of
    common database migration options within `migrator.actor`. This lets you add columns,
    drop columns, migrate types, and the like. For more complex migrations, you can use
    the `migrator.db_session` to run raw SQL queries within the current migration transaction.

    """

    def __init__(self, db_session: AsyncSession):
        self.actor = DatabaseActions(dry_run=False, db_session=db_session)
        self.db_session = db_session

    @classmethod
    @asynccontextmanager
    async def new_migrator(
        cls,
        db_engine: AsyncEngine,
    ):
        sessionmaker = async_sessionmaker(
            db_engine,
            class_=NoCommitAsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        async with sessionmaker() as session:
            yield cls(db_session=session)

            # Now that the migration is done, we should try to commit the session
            session.okay_to_commit = True
            await session.commit()

    async def init_db(self):
        # Create the table if it doesn't exist
        await self.db_session.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS migration_info (
                active_revision VARCHAR(255)
            )
        """
            )
        )
        await self.db_session.flush()

        # Check if the table is empty and insert a default value if necessary
        result = await self.db_session.execute(
            text("SELECT COUNT(*) FROM migration_info")
        )
        count = result.scalar_one()
        if count == 0:
            await self.db_session.execute(
                text("INSERT INTO migration_info (active_revision) VALUES (NULL)")
            )
            await self.db_session.flush()

    async def set_active_revision(self, value: str | None):
        # This will be a no-op if the table doesn't exist
        await self.init_db()

        query = text(
            """
            UPDATE migration_info SET active_revision = :value
        """
        )

        await self.db_session.execute(query, {"value": value})
        await self.db_session.flush()

    async def get_active_revision(self) -> str | None:
        # This will be a no-op if the table doesn't exist
        await self.init_db()

        query = text(
            """
            SELECT active_revision FROM migration_info
        """
        )

        result = await self.db_session.execute(query)
        return cast(str | None, result.scalar_one())
