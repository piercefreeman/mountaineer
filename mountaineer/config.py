from contextlib import contextmanager

from pydantic._internal._model_construction import ModelMetaclass
from pydantic.fields import Field
from pydantic_settings import BaseSettings
from typing_extensions import dataclass_transform


class ConfigMeta(ModelMetaclass):
    def __call__(cls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        register_config(instance)
        return instance


@dataclass_transform(kw_only_default=True, field_specifiers=(Field,))
class ConfigBase(BaseSettings, metaclass=ConfigMeta):
    """
    Base class for the running application's configuration. By convention
    all configuration parameters should be specified here in one payload.
    You'll often call your subclass `ConfigBase`.

    Users are responsible for instantiating an AppConfig with your desired
    settings. This instance will be registered into the global space so it's
    accessible to your controllers. An error will be thrown if you attempt to
    instantiate more than one AppConfig.

    """

    # Name of the python package. Will be used to sniff for the installed
    # codebase in the current virtualenv.
    PACKAGE: str | None = None

    # Environment flag. Set to anything you want. Only if set to "development" will
    # we include frontend artifacts for the hot-reloading server.
    ENVIRONMENT: str = "development"

    model_config = {"frozen": True}


# One global config object
APP_CONFIG: ConfigBase | None = None


def register_config(config: ConfigBase):
    """
    Manually register a configuration instance into the global space. Each application
    can have a maximum of one configuration instance registered. If you attempt to
    register a second instance, an error will be thrown.

    Registration should happen automatically by initializing a new instance of your
    ConfigBase class on application start. This auto-registration is provided by
    the configuration's metaclass in ConfigMeta.

    """
    global APP_CONFIG

    if APP_CONFIG is not None and APP_CONFIG != config:
        raise ValueError("Config already registered")

    APP_CONFIG = config


def unregister_config():
    """
    Unregister the current configuration instance.

    """
    global APP_CONFIG
    APP_CONFIG = None


def get_config() -> ConfigBase:
    """
    Get the current configuration instance that's registered globally. Will
    throw an error if no configuration instance is registered.

    """
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
