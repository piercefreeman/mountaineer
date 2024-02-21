from contextlib import contextmanager

from pydantic._internal._model_construction import ModelMetaclass
from pydantic_settings import BaseSettings


class ConfigMeta(ModelMetaclass):
    def __call__(cls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        register_config(instance)
        return instance


class ConfigBase(BaseSettings, metaclass=ConfigMeta):
    model_config = {"frozen": True}


# One global config object
APP_CONFIG: ConfigBase | None = None


def register_config(config: ConfigBase):
    global APP_CONFIG

    if APP_CONFIG is not None:
        raise ValueError("Config already registered")

    APP_CONFIG = config


def unregister_config():
    global APP_CONFIG
    APP_CONFIG = None


def get_config() -> ConfigBase:
    if APP_CONFIG is None:
        raise ValueError(
            "Configuration not registered. Either:\n"
            "1. Call register_config() with your BaseSettings class\n"
            "2. Make sure your BaseSettings is imported so the ConfigMeta can auto-register"
        )

    return APP_CONFIG


@contextmanager
def register_config_in_context(config: ConfigBase):
    """
    Change the global config object to the given config object
    temporarily. Useful for unit testing.
    """
    global APP_CONFIG
    previous_config = APP_CONFIG
    APP_CONFIG = config
    try:
        yield
    finally:
        APP_CONFIG = previous_config
