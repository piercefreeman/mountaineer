import ast
import importlib
import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Set, Tuple

from mountaineer.logging import setup_logger

logger = setup_logger(__name__)


@dataclass
class DependencyNode:
    module_name: str
    file_path: Path
    last_modified: float
    imports: Set[str] = field(default_factory=set)
    imported_by: Set[str] = field(default_factory=set)
    subclasses: Dict[str, Set[str]] = field(default_factory=dict)
    superclasses: Dict[str, Set[str]] = field(default_factory=dict)
    preserved_state: Dict[int, dict] = field(default_factory=dict)
    submodules: Set[str] = field(default_factory=set)

    def __str__(self):
        return (
            f"DependencyNode({self.module_name}):\n"
            f"  file: {self.file_path}\n"
            f"  imports: {self.imports}\n"
            f"  imported_by: {self.imported_by}\n"
            f"  submodules: {self.submodules}\n"
        )


class HotReloader:
    def __init__(self, root_package: str, package_path: Path, entrypoint: str):
        logger.debug(
            f"Initializing HotReloader with root_package={root_package}, path={package_path}, entrypoint={entrypoint}"
        )
        self.root_package = root_package
        self.package_path = package_path
        self.entrypoint = entrypoint

        sys.path.insert(0, str(package_path.parent))
        sys.path.insert(0, str(package_path))

        self.dependency_graph: Dict[str, DependencyNode] = {}
        self.module_cache: Dict[str, ModuleType] = {}

        # Track module aliases
        self.module_aliases: Dict[str, str] = {}

        # Ensure the entrypoint is imported
        if entrypoint not in sys.modules:
            logger.info(f"Importing entrypoint: {entrypoint}")
            importlib.import_module(entrypoint)
        else:
            logger.info(f"Entrypoint already imported: {entrypoint}")

        # Build the dependency graph by inspecting the already imported modules
        self._build_dependency_graph()
        self._log_dependency_state()

    def _log_dependency_state(self):
        """Log the current state of the dependency graph"""
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
        """Build the dependency graph by inspecting the already imported modules in sys.modules."""
        logger.debug("Building dependency graph from already imported modules.")
        for module_name in sys.modules:
            if module_name.startswith(self.root_package):
                self._import_and_track_module(module_name)
        self._build_inheritance_tree()

    def _track_imports(self, module_path: Path, node: DependencyNode) -> None:
        """Track all imports in a module file."""
        try:
            logger.debug(f"Tracking imports for {module_path}")
            with open(module_path) as f:
                content = f.read()
                tree = ast.parse(content, filename=str(module_path))

            for ast_node in ast.walk(tree):
                if isinstance(ast_node, ast.Import):
                    for name in ast_node.names:
                        logger.debug(f"Found Import in {node.module_name}: {name.name}")
                        if name.name.startswith(self.root_package):
                            node.imports.add(name.name)
                            if name.asname:
                                logger.debug(
                                    f"Recording alias: {name.asname} -> {name.name}"
                                )
                                self.module_aliases[name.asname] = name.name
                            self._ensure_module_loaded(name.name)
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

                    base_module = resolve_relative_import(
                        self.root_package,
                        node.module_name,
                        ast_node.module or "",
                        ast_node.level,
                    )
                    logger.info(f"Resolved base module: {base_module}")

                    if base_module and base_module.startswith(self.root_package):
                        # Handle each imported name
                        for alias in ast_node.names:
                            # Check if the import target is a module
                            potential_module = f"{base_module}.{alias.name}"
                            module_exists = (
                                # potential_module in sys.modules or
                                # self._find_module_file(potential_module) is not None
                                potential_module in sys.modules
                            )

                            # If it's a module, track the full path
                            # If it's a symbol, just track the base module
                            full_import_name = (
                                potential_module if module_exists else base_module
                            )
                            logger.debug(
                                f"Full import name: {full_import_name} (is_module={module_exists})"
                            )

                            # Add to imports
                            node.imports.add(full_import_name)

                            # Handle alias if present
                            if alias.asname:
                                logger.debug(
                                    f"Recording alias: {alias.asname} -> {full_import_name}"
                                )
                                self.module_aliases[alias.asname] = full_import_name

                            # Update imported_by relationship for the imported module
                            # and all its parent modules
                            module_parts = full_import_name.split(".")
                            for i in range(1, len(module_parts) + 1):
                                potential_module = ".".join(module_parts[:i])
                                if potential_module in self.dependency_graph:
                                    logger.info(
                                        f"Marking {potential_module} as imported by {node.module_name}"
                                    )
                                    self.dependency_graph[
                                        potential_module
                                    ].imported_by.add(node.module_name)

            logger.info("=== Final import state ===")
            logger.info(f"Imports: {node.imports}")
            logger.info(f"Imported by: {node.imported_by}")

        except Exception as e:
            logger.error(
                f"Failed to parse imports for {module_path}: {e}", exc_info=True
            )
            raise

    def _ensure_module_loaded(self, module_name: str) -> None:
        if module_name not in self.module_cache:
            if module_name in sys.modules:
                self._import_and_track_module(module_name)
            else:
                logger.debug(f"Module {module_name} is not loaded. Skipping.")

    def _import_and_track_module(self, module_name: str) -> Optional[ModuleType]:
        if module_name not in sys.modules:
            if module_name == self.entrypoint:
                # Import the entrypoint if not already imported
                try:
                    module = importlib.import_module(module_name)
                    sys.modules[module_name] = module
                except Exception as e:
                    logger.error(
                        f"Failed to import entrypoint {module_name}: {e}", exc_info=True
                    )
                    return None
            else:
                # Do not import modules unless they are already imported
                logger.debug(
                    f"Module {module_name} is not loaded and is not the entrypoint. Skipping."
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

                # Track submodule relationship based on path components
                parts = module_name.split(".")
                if len(parts) > 2:  # e.g. pkg.models.example
                    parent_module = ".".join(parts[:-1])  # pkg.models
                    if parent_module in self.dependency_graph:
                        self.dependency_graph[parent_module].submodules.add(module_name)

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

    def _update_inheritance_relationships(self, module_name: str) -> None:
        """Update inheritance relationships for a module after it's loaded."""
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

    def _get_affected_modules(self, changed_module: str) -> Set[str]:
        """Get all modules affected by a change, including submodules."""
        affected = {changed_module}
        to_process = {changed_module}

        while to_process:
            current = to_process.pop()
            if current not in self.dependency_graph:
                continue

            node = self.dependency_graph[current]

            # Add submodules
            # for submodule in node.submodules:
            #    if submodule not in affected:
            #        affected.add(submodule)
            #        to_process.add(submodule)

            # Add modules that import this one (dependents)
            for dependent in node.imported_by:
                if dependent not in affected:
                    affected.add(dependent)
                    to_process.add(dependent)

            # Add parent package if this is a submodule
            # parent_module = ".".join(current.split(".")[:-1])
            # if parent_module and parent_module in self.dependency_graph:
            #    if parent_module not in affected:
            #        affected.add(parent_module)
            #        to_process.add(parent_module)

        return affected

    def _sort_modules_by_dependencies(self, modules: Set[str]) -> List[str]:
        """Sort modules ensuring submodules are reloaded before their parents."""
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

                # Then visit submodules
                for submodule in node.submodules:
                    if submodule in modules:
                        visit(submodule)

            result.append(module_name)

        # Still start with deepest paths first
        modules_list = sorted(modules, key=lambda x: len(x.split(".")), reverse=True)
        for module_name in modules_list:
            visit(module_name)

        return result

    def reload_module(self, module_name: str) -> Tuple[bool, List[str]]:
        return self.reload_modules([module_name])

    def reload_modules(self, module_names: list[str]) -> Tuple[bool, List[str]]:
        """Reload a module and all its dependencies."""
        logger.info(f"=== Starting reload of {module_names} ===")
        self._log_dependency_state()

        reloaded_modules = []
        valid_modules = {
            module_name
            for module_name in module_names
            if module_name in self.module_cache
        }
        invalid_modules = set(module_names) - valid_modules

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
                if mod_name not in sys.modules:
                    logger.warning(f"Module {mod_name} not in sys.modules.")
                    continue

                try:
                    old_module = sys.modules[mod_name]
                    logger.info(f"Reloading {mod_name} (old id: {id(old_module)})")

                    module = importlib.reload(old_module)
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

    def get_module_dependencies(self, module_name: str) -> Dict[str, Any]:
        logger.debug(f"Getting dependencies for {module_name}")
        if module_name not in self.dependency_graph:
            self._import_and_track_module(module_name)

        if module_name not in self.dependency_graph:
            logger.debug(f"Module {module_name} not found in dependency graph")
            return {
                "imports": set(),
                "imported_by": set(),
                "subclasses": {},
                "superclasses": {},
            }

        node = self.dependency_graph[module_name]
        return {
            "imports": node.imports,
            "imported_by": node.imported_by,
            "subclasses": node.subclasses,
            "superclasses": node.superclasses,
        }

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

    def _find_module_file(self, module_name: str) -> Optional[Path]:
        """Find the file path for a module, handling packages and submodules."""
        module_parts = module_name.split(".")
        relative_parts = module_parts[1:]  # Skip root package
        current_path = self.package_path

        for part in relative_parts:
            current_path = current_path / part

            # Check if it's a package
            init_file = current_path / "__init__.py"
            if init_file.exists():
                if part == relative_parts[-1]:  # This is our target
                    return init_file
                continue

            # Check if it's a module
            module_file = current_path.parent / f"{part}.py"
            if module_file.exists():
                return module_file

        return None


def resolve_relative_import(
    root_package: str, module_name: str, relative_path: str, level: int
) -> Optional[str]:
    """
    Resolve relative and absolute imports to their full module path.
    Args:
        root_package: The root package name (e.g., 'my_package')
        module_name: The current module's full name (e.g., 'my_package.sub.module')
        relative_path: The relative import path (e.g., 'submodule')
        level: The number of dots in the relative import (0 for absolute imports)
    Returns:
        The resolved full module path or None if invalid
    """
    logger.debug(
        f"Resolving import: module={module_name}, path={relative_path}, level={level}"
    )

    # Handle invalid level
    if level < 0:
        logger.warning(f"Invalid negative level {level}")
        return None

    # Handle absolute imports (level = 0)
    if level == 0:
        if not relative_path:
            return root_package
        if relative_path.startswith(root_package):
            return relative_path
        return f"{root_package}.{relative_path}"

    parts = module_name.split(".")

    # Handle invalid level that's too high
    if level > len(parts):
        logger.warning(
            f"Invalid relative import: level {level} too high for module {module_name}"
        )
        return None

    # For __init__.py, we're already at the package level
    if parts[-1] == "__init__":
        parts = parts[:-1]

    # Get base path by removing the right number of components
    # level=1: use current directory
    # level=2: remove one directory
    # level=3: remove two directories
    # etc.
    if level == 1:
        # For single dot, use full path up to current directory
        base_path = ".".join(parts)
    else:
        # For multiple dots, remove (level-1) components
        base_path = ".".join(parts[: -(level - 1)])

    # Handle empty base path (we've gone up to root)
    if not base_path:
        base_path = root_package

    # Build final path
    if not relative_path:
        return base_path
    return f"{base_path}.{relative_path}"
