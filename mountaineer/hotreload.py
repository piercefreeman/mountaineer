import ast
import importlib
import importlib.util
import inspect
import os
import sys
import time
from dataclasses import dataclass, field
from importlib.abc import SourceLoader
from pathlib import Path
from types import ModuleType

from mountaineer.logging import setup_internal_logger

logger = setup_internal_logger(__name__)


@dataclass
class DependencyNode:
    module_name: str
    file_path: Path
    last_modified: float
    imports: set[str] = field(default_factory=set)
    imported_by: set[str] = field(default_factory=set)
    subclasses: dict[str, set[str]] = field(default_factory=dict)
    superclasses: dict[str, set[str]] = field(default_factory=dict)

    def __str__(self):
        return (
            f"DependencyNode({self.module_name}):\n"
            f"  file: {self.file_path}\n"
            f"  imports: {self.imports}\n"
            f"  imported_by: {self.imported_by}\n"
        )


class HotReloader:
    def __init__(self, root_package: str, package_path: Path, entrypoint: str):
        logger.debug(
            f"Initializing HotReloader with root_package={root_package}, path={package_path}, entrypoint={entrypoint}"
        )
        self.root_package = root_package
        self.package_path = package_path
        self.entrypoint = entrypoint
        self.allow_manual_import = False

        sys.path.insert(0, str(package_path.parent))
        sys.path.insert(0, str(package_path))

        self.dependency_graph: dict[str, DependencyNode] = {}
        self.module_cache: dict[str, ModuleType] = {}

        # Ensure the entrypoint is imported
        if entrypoint not in sys.modules:
            logger.info(f"Importing entrypoint: {entrypoint}")
            importlib.import_module(entrypoint)
        else:
            logger.info(f"Entrypoint already imported: {entrypoint}")

        # Build the dependency graph by inspecting the already imported modules
        self._build_dependency_graph()
        self._log_dependency_state()

        # Once the initial graph is built, anything else that is tracked (like a new file)
        # will have to be imported manually
        self.allow_manual_import = True

    def _log_dependency_state(self):
        """
        Log the current state of the dependency graph

        """
        logger.info("Current Dependency Graph State:")
        for module_name, node in self.dependency_graph.items():
            logger.info(str(node))
            logger.info(
                f"Module cache ID for {module_name}: {id(self.module_cache.get(module_name))}"
            )
            if module_name in sys.modules:
                logger.info(
                    f"sys.modules ID for {module_name}: {id(sys.modules[module_name])}"
                )

    def _build_dependency_graph(self) -> None:
        """
        Build the dependency graph by inspecting the already imported modules in sys.modules.

        """
        logger.debug("Building dependency graph from already imported modules.")
        static_modules = [module_name for module_name in sys.modules]
        for module_name in static_modules:
            if module_name.startswith(self.root_package):
                self._import_and_track_module(module_name)
        self._build_inheritance_tree()

    def _import_and_track_module(self, module_name: str) -> ModuleType | None:
        if module_name not in sys.modules:
            if self.allow_manual_import:
                # Import the entrypoint if not already imported
                try:
                    module = importlib.import_module(module_name)
                    sys.modules[module_name] = module
                except Exception as e:
                    logger.error(
                        f"Failed to import new module {module_name}: {e}", exc_info=True
                    )
                    return None
            else:
                # Do not import modules unless they are already imported
                logger.debug(
                    f"Module {module_name} is not loaded and manual loading is not allowed. Skipping."
                )
                return None

        try:
            module = sys.modules[module_name]

            # Determine the module path
            module_parts = module_name.split(".")
            relative_parts = module_parts[1:]
            relative_path = Path(*relative_parts)

            # First, check if it's a package (directory with __init__.py)
            package_init = self.package_path / relative_path / "__init__.py"
            if package_init.exists():
                module_path = package_init
            else:
                # Else, assume it's a module (.py file)
                module_py = self.package_path / relative_path.with_suffix(".py")
                if module_py.exists():
                    module_path = module_py
                else:
                    logger.error(
                        f"Found module {module_name} path not resolved, proposed {module_py}"
                    )
                    return None

            # Create/update node
            if module_name not in self.dependency_graph:
                node = DependencyNode(
                    module_name=module_name,
                    file_path=module_path,
                    last_modified=module_path.stat().st_mtime,
                )
                self.dependency_graph[module_name] = node

            else:
                node = self.dependency_graph[module_name]
                # Clear imports and inheritance relationships
                node.imports.clear()
                node.subclasses.clear()
                node.superclasses.clear()

            self.module_cache[module_name] = module

            # Now track imports and inheritance
            self._track_imports(module_path, node)
            self._update_inheritance_relationships(module_name)

            return module

        except Exception as e:
            logger.error(f"Failed to process module {module_name}: {e}", exc_info=True)
            if module_name in self.dependency_graph:
                del self.dependency_graph[module_name]
            return None

    def _track_imports(self, module_path: Path, node: DependencyNode) -> None:
        """
        Track all imports in a module file.

        """
        try:
            logger.debug(f"Tracking imports for {module_path}")
            with open(module_path) as f:
                content = f.read()
                tree = ast.parse(content, filename=str(module_path))

            for ast_node in ast.walk(tree):
                if isinstance(ast_node, ast.Import):
                    for name in ast_node.names:
                        logger.debug(f"Found import in {node.module_name}: {name.name}")
                        if name.name.startswith(self.root_package):
                            node.imports.add(name.name)
                            if name.name in self.dependency_graph:
                                self.dependency_graph[name.name].imported_by.add(
                                    node.module_name
                                )

                elif isinstance(ast_node, ast.ImportFrom):
                    logger.info("Found ImportFrom:")
                    logger.info(f"  Module: {ast_node.module}")
                    logger.info(f"  Level: {ast_node.level}")
                    logger.info(
                        f"  Names: {[n.name + (' as ' + n.asname if n.asname else '') for n in ast_node.names]}"
                    )

                    for import_element in ast_node.names:
                        absolute_module = resolve_relative_import(
                            root_package=self.root_package,
                            current_module=node.module_name,
                            from_import=ast_node.module or "",
                            from_import_level=ast_node.level,
                            sys_modules=set(sys.modules.keys()),
                            import_name=import_element.name,
                        )
                        logger.info(f"Resolved base module: {absolute_module}")

                        if not absolute_module:
                            continue

                        # Add to imports
                        node.imports.add(absolute_module)

                        if absolute_module in self.dependency_graph:
                            logger.info(
                                f"Marking {absolute_module} as imported by {node.module_name}"
                            )
                            self.dependency_graph[absolute_module].imported_by.add(
                                node.module_name
                            )

            logger.info("=== Final import state ===")
            logger.info(f"Imports: {node.imports}")
            logger.info(f"Imported by: {node.imported_by}")

        except Exception as e:
            logger.error(
                f"Failed to parse imports for {module_path}: {e}", exc_info=True
            )
            raise

    def _update_inheritance_relationships(self, module_name: str) -> None:
        """
        Update inheritance relationships for a module after it's loaded.

        """
        if module_name not in self.module_cache:
            return

        module = self.module_cache[module_name]
        node = self.dependency_graph[module_name]

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if not obj.__module__.startswith(self.root_package):
                continue

            for base in obj.__bases__:
                if base.__module__.startswith(self.root_package):
                    base_module = base.__module__
                    base_name = base.__name__

                    if base_module in self.dependency_graph:
                        base_node = self.dependency_graph[base_module]
                        if base_name not in base_node.subclasses:
                            base_node.subclasses[base_name] = set()
                        base_node.subclasses[base_name].add(name)

                    if name not in node.superclasses:
                        node.superclasses[name] = {base_name}
                    else:
                        node.superclasses[name].add(base_name)

    def _get_affected_modules(self, changed_module: str) -> set[str]:
        """
        Get all modules affected by a change. For now we assume that any file
        that imports modified files is affected, which is recursively true
        for the whole project.

        """
        affected = {changed_module}
        to_process = {changed_module}

        while to_process:
            current = to_process.pop()
            if current not in self.dependency_graph:
                continue

            node = self.dependency_graph[current]

            # Add modules that import this one (dependents)
            for dependent in node.imported_by:
                if dependent not in affected:
                    affected.add(dependent)
                    to_process.add(dependent)

        return affected

    def _sort_modules_by_dependencies(self, modules: set[str]) -> list[str]:
        """
        Sort modules ensuring parent modules are reloaded before their children.

        """
        result = []
        visited = set()

        def visit(module_name: str):
            if module_name in visited:
                return
            # Don't skip non-sys.modules modules! We need example.py
            visited.add(module_name)

            # First visit imports since they're the deepest dependencies
            if module_name in self.dependency_graph:
                node = self.dependency_graph[module_name]
                for imp in node.imports:
                    if imp in modules:  # Make sure it's an affected module
                        visit(imp)

            result.append(module_name)

        # Still start with deepest paths first
        modules_list = sorted(modules, key=lambda x: len(x.split(".")), reverse=True)
        for module_name in modules_list:
            visit(module_name)

        return result

    def reload_module(self, module_name: str) -> tuple[bool, list[str]]:
        return self.reload_modules([module_name])

    def reload_modules(self, module_names: list[str]) -> tuple[bool, list[str]]:
        """
        Reload a module and all its dependencies. Note that this requires the underlying bite
        length to have changed: https://bugs.python.org/issue31772

        """
        logger.info(f"=== Starting reload of {module_names} ===")
        self._log_dependency_state()

        # Try to import any modules that haven't been indexed yet
        valid_modules: set[str] = set()
        for module_name in module_names:
            if module_name not in self.module_cache:
                module = self._import_and_track_module(module_name)
                if module:
                    valid_modules.add(module_name)
            else:
                valid_modules.add(module_name)

        reloaded_modules: list[str] = []
        invalid_modules = set(module_names) - valid_modules

        # Flag an error on any errors but continue reloading the ones that we're
        # able to find
        if invalid_modules:
            logger.error(f"Modules {invalid_modules} are not loaded. Cannot reload.")

            if not valid_modules:
                return False, reloaded_modules

        try:
            affected = {
                dependency
                for module_name in valid_modules
                for dependency in self._get_affected_modules(module_name)
            }
            logger.info(f"Affected modules: {affected}")
            sorted_modules = self._sort_modules_by_dependencies(affected)
            logger.info(f"Reload order: {sorted_modules}")

            for mod_name in sorted_modules:
                try:
                    old_module = sys.modules[mod_name]
                    logger.info(f"Reloading {mod_name} (old id: {id(old_module)})")

                    module = safe_reload(old_module)
                    logger.info(f"Reloaded {mod_name} (new id: {id(module)})")

                    # Update cache and track reload
                    self.module_cache[mod_name] = module
                    reloaded_modules.append(mod_name)

                except Exception as e:
                    logger.error(f"Failed to reload {mod_name}: {e}", exc_info=True)
                    return False, reloaded_modules

            logger.info("=== Rebuilding inheritance tree ===")
            self._build_inheritance_tree()
            self._log_dependency_state()

            return True, reloaded_modules

        except Exception as e:
            logger.error(f"Failed to reload {valid_modules}: {e}", exc_info=True)
            return False, reloaded_modules

    def get_module_dependencies(self, module_name: str):
        """
        Helper function for clients to access the current DAG node of a module. We return a sythetic
        DAG with no dependencies.

        """
        logger.debug(f"Getting dependencies for {module_name}")
        if module_name not in self.dependency_graph:
            self._import_and_track_module(module_name)

        if module_name not in self.dependency_graph:
            logger.debug(f"Module {module_name} not found in dependency graph")
            return None

        return self.dependency_graph[module_name]

    def _build_inheritance_tree(self) -> None:
        for module_name, module in self.module_cache.items():
            node = self.dependency_graph[module_name]
            node.subclasses.clear()
            node.superclasses.clear()

        for module_name, module in self.module_cache.items():
            node = self.dependency_graph[module_name]
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if not obj.__module__.startswith(self.root_package):
                    continue

                for base in obj.__bases__:
                    if base.__module__.startswith(self.root_package):
                        base_module = base.__module__
                        base_name = base.__name__

                        if base_module in self.dependency_graph:
                            base_node = self.dependency_graph[base_module]
                            if base_name not in base_node.subclasses:
                                base_node.subclasses[base_name] = set()
                            base_node.subclasses[base_name].add(name)

                        if name not in node.superclasses:
                            node.superclasses[name] = {base_name}
                        else:
                            node.superclasses[name].add(base_name)


def resolve_relative_import(
    *,
    root_package: str,
    current_module: str,
    from_import: str,
    from_import_level: int,
    import_name: str,
    sys_modules: set[str],
) -> str | None:
    """
    Resolves the absolute module name for a potentially relative import. Let's consider some
    different forms that an import can take:

    from myfile import MyClass
    from mymodule import myfile
    from .myfile import MyClass
    from ..mymodule import myfile
    from mypackage.mymodule import myfile

    The general structure is:

    from {dots:from_import_level}{from_import} import {import_name}

    """

    # Handle invalid level
    if from_import_level < 0:
        logger.warning(f"Invalid negative level {from_import_level}")
        return None

    # Handle absolute imports or local path imports (level = 0)
    if from_import_level == 0:
        # Prioritize local path imports, then absolute imports
        proposed_components = [
            # Local path - import name as a module
            [current_module, from_import, import_name],
            # Local path - import name as a class/function
            [current_module, from_import],
            # Absolute import - import name as a module
            [from_import, import_name],
            # Absolute import - import name as a class/function
            [from_import],
        ]
        proposed_paths = [
            ".".join([component for component in components if component.strip()])
            for components in proposed_components
        ]

        for absolute_path in proposed_paths:
            if absolute_path in sys_modules:
                return absolute_path

        # Otherwise, we can't find the module
        logger.warning(
            f"No matching level-0 modules found in sys.modules, tried: {proposed_paths}"
        )
        return None

    parts = current_module.split(".")

    # Handle invalid level that's too high and goes outside of the package
    if from_import_level > len(parts):
        logger.warning(
            f"Invalid relative import: level {from_import_level} too high for module {current_module}"
        )
        return None

    # __init__ files should just map to their parent module
    if parts[-1] == "__init__":
        parts = parts[:-1]

    # Get base path by removing the right number of components
    # level=1: use current directory
    # level=2: remove one directory
    # level=3: remove two directories
    # etc.
    if from_import_level == 1:
        # For single dot, use the current directory
        base_path = ".".join(parts)
    else:
        # For multiple dots, remove (level-1) components
        base_path = ".".join(parts[: -(from_import_level - 1)])

    # Handle empty base path (we've gone up to root)
    if not base_path:
        base_path = root_package

    # Build final path - at this point the level should be 0
    return resolve_relative_import(
        root_package=root_package,
        current_module=base_path,
        from_import=from_import,
        from_import_level=0,
        import_name=import_name,
        sys_modules=sys_modules,
    )


def safe_reload(module: ModuleType) -> ModuleType:
    """
    Safely reload a module, ensuring bytecode is regenerated when the source file
    has been modified, even within the same second. Local fix for https://bugs.python.org/issue31772

    Since this only runs in the hot-path for development code, the additional os stat overhead
    isn't meaningful.

    :param module: The module to reload

    """
    # Get the module spec
    spec = importlib.util.find_spec(module.__name__)
    if not spec or not spec.origin:
        return importlib.reload(module)

    # Remove any cached bytecode if source mtime matches current time
    source_path = spec.origin
    if source_path.endswith(".py"):
        # Clear out the bytecode to force recompilation
        current_time = int(time.time())
        try:
            if spec.loader and isinstance(spec.loader, SourceLoader):
                source_mtime = int(spec.loader.path_stats(source_path)["mtime"])
                if source_mtime == current_time:
                    bytecode_path = importlib.util.cache_from_source(source_path)
                    os.remove(bytecode_path)
        except (AttributeError, OSError, KeyError):
            pass

    return importlib.reload(module)
