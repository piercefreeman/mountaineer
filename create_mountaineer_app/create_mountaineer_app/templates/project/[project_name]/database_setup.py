{% if create_stub_files %}
from fastapi import Depends
from iceaxe import DBConnection, select
from iceaxe.mountaineer import DatabaseDependencies
from pydantic import BaseModel

from {{project_name}} import models

CREATEDB_COMMAND = "{% if package_manager == 'venv' %}createdb{% else %}uv run createdb{% endif %}"


class DatabaseSetupRequired(BaseModel):
    createdb_command: str = CREATEDB_COMMAND


def _is_missing_relation_error(exc: Exception) -> bool:
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate == "42P01":
        return True

    message = str(exc).lower()
    return "relation" in message and "does not exist" in message


async def get_database_setup_required(
    session: DBConnection = Depends(DatabaseDependencies.get_db_connection),
) -> DatabaseSetupRequired | None:
    try:
        await session.exec(select(models.DetailItem).limit(1))
    except Exception as exc:
        if _is_missing_relation_error(exc):
            return DatabaseSetupRequired()
        raise

    return None
{% endif %}
