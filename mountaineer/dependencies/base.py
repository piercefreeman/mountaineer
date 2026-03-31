import warnings

from mountaineer_di import (
    get_function_dependencies as get_function_dependencies,
    isolate_dependency_only_function as isolate_dependency_only_function,
    strip_depends_from_signature as strip_depends_from_signature,
)


class DependenciesBaseMeta(type):
    """
    Dependencies have to be appended to their wrapper class explicitly. Providing static
    methods confuses the FastAPI resolution pipeline, because staticfunctions don't properly
    inspect as coroutines.

    Within `solve_dependencies`, it relies on function inspection to determine whether it should
    be run in the async loop or a separate thread. Executing `is_coroutine_callable` with a static
    method will always returns False, so we will inadvertantly run async dependencies in a thread
    loop. This will just return the raw coroutine instead of actually resolving the dependency.

    Adding functions to the class directly will just link their function signatures, which
    will inspect as intended.

    """

    def __new__(cls, name, bases, namespace, **kwargs):
        # Flag any child instances as deprecated but not the base model
        if name != "DependenciesBase":
            warnings.warn(
                (
                    "DependenciesBase is deprecated and will be removed in a future version.\n"
                    "Import modules to form dependencies. See mountaineer.dependencies.core for an example."
                ),
                DeprecationWarning,
                stacklevel=2,
            )

        for attr_name, attr_value in namespace.items():
            if isinstance(attr_value, staticmethod):
                raise TypeError(
                    f"Static methods are not allowed in dependency wrapper '{name}'. Found static method: '{attr_name}'."
                )
        return super().__new__(cls, name, bases, namespace, **kwargs)


class DependenciesBase(metaclass=DependenciesBaseMeta):
    pass
