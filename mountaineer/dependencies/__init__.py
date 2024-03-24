from . import core as CoreDependencies  # noqa: F401
from .base import (
    DependenciesBase as DependenciesBase,
    get_function_dependencies as get_function_dependencies,
    isolate_dependency_only_function as isolate_dependency_only_function,
)
