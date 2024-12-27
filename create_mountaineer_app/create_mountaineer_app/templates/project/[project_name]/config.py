from mountaineer import ConfigBase
from iceaxe.mountaineer import DatabaseConfig
from pydantic_settings import SettingsConfigDict

class AppConfig(ConfigBase, DatabaseConfig):
    PACKAGE: str | None = "{{project_name}}"

    model_config = SettingsConfigDict(env_file=(".env",))
