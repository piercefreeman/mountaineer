from fastapi import Depends
from filzl.database import DatabaseDependencies
from sqlalchemy.ext.asyncio import AsyncEngine

from filzl_daemons.db import PostgresBackend
from filzl_daemons.models import LocalModelDefinition
from filzl_daemons.workflow import DaemonClient


class DaemonDependencies:
    @staticmethod
    def get_daemon_backend(local_models: LocalModelDefinition):
        def inner(
            engine: AsyncEngine = Depends(DatabaseDependencies.get_db),
        ):
            return PostgresBackend(engine=engine, local_models=local_models)

        return inner

    @staticmethod
    def get_daemon_client(local_models: LocalModelDefinition):
        def inner(
            backend: PostgresBackend = Depends(
                DaemonDependencies.get_daemon_backend(local_models)
            ),
        ):
            return DaemonClient(backend=backend)

        return inner
