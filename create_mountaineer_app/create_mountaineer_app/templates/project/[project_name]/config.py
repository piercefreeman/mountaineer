from mountaineer import ConfigBase
from mountaineer.database import DatabaseConfig
from pydantic_settings import SettingsConfigDict

class AppConfig(ConfigBase, DatabaseConfig):

    model_config = SettingsConfigDict(env_file=(".env",))
