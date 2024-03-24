from mountaineer.database.config import DatabaseConfig


class ExampleDatabaseConfig(DatabaseConfig):
    POSTGRES_HOST: str = "localhost"
    POSTGRES_USER: str = "mountaineer"
    POSTGRES_PASSWORD: str = "raw_password"
    POSTGRES_DB: str = "mountaineer"


def test_allows_default_params():
    """
    Test that the config model should merge the default and the runtime
    provided values, with a preference to runtime values.

    """
    config = ExampleDatabaseConfig(POSTGRES_PASSWORD="password")

    assert config.POSTGRES_PASSWORD == "password"
    assert "password_raw" not in str(config.SQLALCHEMY_DATABASE_URI)
