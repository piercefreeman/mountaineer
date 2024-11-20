import ast
import importlib
import inspect
import sys
from dataclasses import dataclass, field
from enum import Enum
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

        # Ensure the entrypoint is imported
        if entrypoint not in sys.modules:
            print(f"Importing entrypoint: {entrypoint}")
            importlib.import_module(entrypoint)
        else:
            print(f"Entrypoint already imported: {entrypoint}")

        print("Found sys modules: ", [key for key in sys.modules.keys() if key.startswith(root_package)])

        # Build the dependency graph by inspecting the already imported modules
        self._build_dependency_graph()

        print("Dependency graph: ", self.dependency_graph)

    def _build_dependency_graph(self) -> None:
        """Build the dependency graph by inspecting the already imported modules in sys.modules."""
        logger.debug("Building dependency graph from already imported modules.")
        for module_name in sys.modules:
            if module_name.startswith(self.root_package):
                self._import_and_track_module(module_name)
        self._build_inheritance_tree()

    def _track_imports(self, module_path: Path, node: DependencyNode) -> None:
        try:
            with open(module_path) as f:
                content = f.read()
                tree = ast.parse(content, filename=str(module_path))

            for ast_node in ast.walk(tree):
                if isinstance(ast_node, ast.Import):
                    for name in ast_node.names:
                        if name.name.startswith(self.root_package):
                            logger.debug(f"Found import: {name.name}")
                            node.imports.add(name.name)
                            self._ensure_module_loaded(name.name)
                            if name.name in self.dependency_graph:
                                self.dependency_graph[name.name].imported_by.add(
                                    node.module_name
                                )

                elif isinstance(ast_node, ast.ImportFrom):
                    module_name = ''
                    if ast_node.module:
                        if ast_node.level == 0:
                            module_name = ast_node.module
                        else:
                            # Handle relative imports
                            parent_module_parts = node.module_name.split('.')[:-ast_node.level]
                            module_name = '.'.join(parent_module_parts + [ast_node.module])

                    if module_name.startswith(self.root_package):
                        # Track the module itself
                        logger.debug(f"Found module import: {module_name}")
                        node.imports.add(module_name)
                        self._ensure_module_loaded(module_name)
                        if module_name in self.dependency_graph:
                            self.dependency_graph[module_name].imported_by.add(
                                node.module_name
                            )

                        # Track specific imports
                        for alias in ast_node.names:
                            imported_name = alias.name
                            full_import = f"{module_name}.{imported_name}"
                            logger.debug(f"Found from import: {full_import}")
                            node.imports.add(full_import)
                            self._ensure_module_loaded(full_import)
                            if full_import in self.dependency_graph:
                                self.dependency_graph[full_import].imported_by.add(
                                    node.module_name
                                )

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
                    logger.error(f"Failed to import entrypoint {module_name}: {e}", exc_info=True)
                    return None
            else:
                # Do not import modules unless they are already imported
                logger.debug(f"Module {module_name} is not loaded and is not the entrypoint. Skipping.")
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
                    logger.error(f"Found module {module_name} path not resolved, proposed {module_py}")
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
        affected = {changed_module}
        to_process = {changed_module}

        while to_process:
            current = to_process.pop()
            if current not in self.dependency_graph:
                continue

            node = self.dependency_graph[current]

            for dependent in node.imported_by:
                if dependent not in affected:
                    affected.add(dependent)
                    to_process.add(dependent)

            # Check inheritance relationships
            for class_name in node.subclasses:
                for subclass in node.subclasses[class_name]:
                    subclass_module = None
                    # Find the module where this subclass is defined
                    for mod_name, mod_node in self.dependency_graph.items():
                        if subclass in mod_node.superclasses:
                            subclass_module = mod_name
                            break
                    if subclass_module and subclass_module not in affected:
                        affected.add(subclass_module)
                        to_process.add(subclass_module)

        return affected

    def _sort_modules_by_dependencies(self, modules: Set[str]) -> List[str]:
        result = []
        visited = set()

        def visit(module_name: str):
            if module_name in visited or module_name not in self.dependency_graph:
                return
            visited.add(module_name)
            node = self.dependency_graph[module_name]
            for imp in node.imports:
                if imp in modules:
                    visit(imp)
            for superclass_modules in node.superclasses.values():
                for super_class in superclass_modules:
                    super_module = None
                    # Find the module where this superclass is defined
                    for mod_name, mod_node in self.dependency_graph.items():
                        if super_class in mod_node.subclasses:
                            super_module = mod_name
                            break
                    if super_module and super_module in modules:
                        visit(super_module)

            result.append(module_name)

        for module_name in modules:
            visit(module_name)

        return result

    def reload_module(self, module_name: str) -> Tuple[bool, List[str]]:
        logger.debug(f"Reloading module: {module_name}")
        reloaded_modules = []
        try:
            if module_name not in self.module_cache:
                logger.error(f"Module {module_name} is not loaded. Cannot reload.")
                return False, reloaded_modules

            # Proceed to reload the module and its dependencies
            affected = self._get_affected_modules(module_name)
            logger.debug(f"Affected modules: {affected}")
            sorted_modules = self._sort_modules_by_dependencies(affected)
            logger.debug(f"Sorted modules: {sorted_modules}")

            for mod_name in sorted_modules:
                if mod_name not in sys.modules:
                    logger.warning(f"Module {mod_name} is not loaded. Skipping reload.")
                    continue

                try:
                    old_module = sys.modules[mod_name]

                    # Reload the module
                    logger.debug(f"Reloading {mod_name}")
                    print(f"RELOADING {mod_name}", id(old_module))
                    module = importlib.reload(old_module)
                    print(f"RELOADED {mod_name}", id(module))

                    #import inspect
                    #print(inspect.getsource(module))

                    sys.modules[mod_name] = module
                    self.module_cache[mod_name] = module

                    #self.module_cache[mod_name] = module

                    reloaded_modules.append(mod_name)

                except SyntaxError as e:
                    logger.error(f"Syntax error in {mod_name}: {e}")
                    return False, reloaded_modules

                except Exception as e:
                    logger.error(f"Failed to reload {mod_name}: {e}", exc_info=True)
                    # Non-syntax error during reload
                    # Remove all dependent modules from sys.modules
                    for dep_mod_name in sorted_modules:
                        if dep_mod_name in sys.modules:
                            del sys.modules[dep_mod_name]
                            if dep_mod_name in self.module_cache:
                                del self.module_cache[dep_mod_name]
                            if dep_mod_name in self.dependency_graph:
                                del self.dependency_graph[dep_mod_name]

                    # Re-import the entrypoint
                    self._import_and_track_module(self.entrypoint)

                    return False, reloaded_modules

            # Rebuild inheritance tree after reloading
            self._build_inheritance_tree()

            return True, reloaded_modules

        except Exception as e:
            logger.error(f"Failed to reload {module_name}: {e}", exc_info=True)
            # Remove all dependent modules from sys.modules
            for mod_name in sorted_modules:
                if mod_name in sys.modules:
                    del sys.modules[mod_name]
                    if mod_name in self.module_cache:
                        del self.module_cache[mod_name]
                    if mod_name in self.dependency_graph:
                        del self.dependency_graph[mod_name]

            # Re-import the entrypoint
            self._import_and_track_module(self.entrypoint)

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
