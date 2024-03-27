from typing import Type, TypeVar

from pydantic_settings import BaseSettings

from mountaineer.config import get_config

T = TypeVar("T", bound=BaseSettings)


def get_config_with_type(required_type: Type[T]):
    """
    For use in dependency injection. Will retrieve your
    registered ConfigBase from the global registry and ensure
    that it conforms to the requested type.

    ```python
    async def render(
        self,
        config: AppConfig = Depends(CoreDependencies.get_config_with_type(AppConfig))
    ):
        ...
    ```

    :param required_type: Assert the config class implements this interface. Allows
        for flexible use of multiple BaseSettings to manage different parts of your
        application code.

    """

    def internal_dependency() -> T:
        config = get_config()
        if not isinstance(config, required_type):
            raise TypeError(
                f"Expected config to inherit from {required_type}, {type(config)} is not a valid subclass"
            )
        return config

    return internal_dependency
