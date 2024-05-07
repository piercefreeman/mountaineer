from abc import abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from mountaineer.dependencies import get_function_dependencies
from mountaineer.migrations.migrator import Migrator


class MigrationAsyncSession(AsyncSession):
    """
    Internal Mountaineer session to disallow clients from using
    the commit() method.

    """

    async def commit(self):
        raise NotImplementedError(
            "Commit isn't supported during migrations, since we need to wrap the whole transaction chain in a single transaction."
        )


class MigrationRevisionBase:
    """
    Base class for all revisions. Both the "up" and the "down"
    also accepts all dependency injection values.

    """

    # up and down revision are both set, except for the initial revision
    # where down_revision is None
    up_revision: str
    down_revision: str | None

    async def handle_up(self):
        async with get_function_dependencies(
            callable=self.up,
        ) as values:
            if "migrator" not in values:
                raise ValueError(
                    "The 'migrator' dependency is required for migrations."
                )

            await self.up(**values)

            migrator = values["migrator"]
            await migrator.set_active_revision(self.up_revision)

    async def handle_down(self):
        async with get_function_dependencies(
            callable=self.down,
        ) as values:
            if "migrator" not in values:
                raise ValueError(
                    "The 'migrator' dependency is required for migrations."
                )

            await self.down(**values)

            migrator = values["migrator"]
            await migrator.set_active_revision(self.down_revision)

    @abstractmethod
    async def up(self, migrator: Migrator):
        pass

    @abstractmethod
    async def down(self, migrator: Migrator):
        pass
