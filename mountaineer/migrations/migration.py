from abc import abstractmethod

from mountaineer.dependencies import get_function_dependencies
from mountaineer.migrations.migrator import Migrator


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
        """
        Internal method to handle the up migration.
        """
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
        """
        Internal method to handle the down migration.
        """
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
        """
        Perform the migration "up" action. Clients should place their
        migration logic here.

        """
        pass

    @abstractmethod
    async def down(self, migrator: Migrator):
        """
        Perform the migration "down" action. Clients should place their
        migration logic here.

        """
        pass
