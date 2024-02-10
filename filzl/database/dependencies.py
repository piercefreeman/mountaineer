from fastapi import Depends
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from filzl.database.config import DatabaseConfig
from filzl.dependencies import CoreDependencies


class DatabaseDependencies:
    """
    Dependencies for use in API endpoint routes.

    """

    @staticmethod
    def get_db(
        config: DatabaseConfig = Depends(
            CoreDependencies.get_config_with_type(DatabaseConfig)
        ),
    ):
        if not config.SQLALCHEMY_DATABASE_URI:
            raise RuntimeError("No SQLALCHEMY_DATABASE_URI set")

        return create_engine(str(config.SQLALCHEMY_DATABASE_URI))

    @staticmethod
    def get_db_session(
        engine: Engine = Depends(get_db),
    ):
        with Session(engine) as session:
            yield session
