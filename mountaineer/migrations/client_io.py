"""
Client interface functions to introspect the client migrations and import them appropriately
into the current runtime.

"""

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from mountaineer.migrations.migration import MigrationRevisionBase


def fetch_migrations(migration_base: Path):
    """
    Fetch all migrations from the migration base directory. Instead of using importlib.import_module,
    we manually create the module dependencies - this provides some flexibility in the future to avoid
    importing the whole client application just to fetch the migrations.

    We enforce that all migration files have the prefix 'rev_'.

    """
    migrations: list[MigrationRevisionBase] = []
    for file in migration_base.glob("rev_*.py"):
        module_name = file.stem
        if module_name.isidentifier() and not module_name.startswith("_"):
            spec = spec_from_file_location(module_name, str(file))
            if spec and spec.loader:
                module = module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                migrations.extend(
                    attribute()
                    for attribute_name in dir(module)
                    if isinstance(attribute := getattr(module, attribute_name), type)
                    and issubclass(attribute, MigrationRevisionBase)
                    and attribute is not MigrationRevisionBase
                )
    return migrations


def sort_migrations(migrations: list[MigrationRevisionBase]):
    """
    Sort migrations by their (down_revision, up_revision) dependencies. We start with down=current_revision
    which should be the original migration.

    """
    migration_dict = {mig.down_revision: mig for mig in migrations}
    sorted_revisions: list[MigrationRevisionBase] = []

    next_revision = None
    while next_revision in migration_dict:
        next_migration = migration_dict[next_revision]
        sorted_revisions.append(next_migration)
        next_revision = next_migration.up_revision

    if len(sorted_revisions) != len(migrations):
        raise ValueError(
            "There are gaps in the migration sequence or unresolved dependencies."
        )

    return sorted_revisions
