from typing import Type, TypeVar

from pydantic_settings import BaseSettings

from mountaineer.config import get_config

T = TypeVar("T", bound=BaseSettings)


def get_config_with_type(required_type: Type[T]):
    def internal_dependency() -> T:
        config = get_config()
        if not isinstance(config, required_type):
            raise TypeError(
                f"Expected config to inherit from {required_type}, {type(config)} is not a valid subclass"
            )
        return config

    return internal_dependency
