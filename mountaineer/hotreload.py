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
    def __init__(self, root_package: str, package_path: Path):
        logger.debug(
            f"Initializing HotReloader with root_package={root_package}, path={package_path}"
        )
        self.root_package = root_package
        self.package_path = package_path

        sys.path.insert(0, str(package_path.parent))
        sys.path.insert(0, str(package_path))

        self.dependency_graph: Dict[str, DependencyNode] = {}
        self.module_cache: Dict[str, ModuleType] = {}

        # package_init = package_path / "__init__.py"
        # if package_init.exists():
        #     self.dependency_graph[root_package] = DependencyNode(
        #         module_name=root_package,
        #         file_path=package_init,
        #         last_modified=package_init.stat().st_mtime,
        #     )
        #     self.module_cache[root_package] = importlib.import_module(root_package)

        self._scan_package_structure()

        print("DEPENDENCIES", self.dependency_graph)

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
                    if ast_node.module and ast_node.module.startswith(
                        self.root_package
                    ):
                        # Track the module itself
                        logger.debug(f"Found module import: {ast_node.module}")
                        node.imports.add(ast_node.module)
                        self._ensure_module_loaded(ast_node.module)
                        if ast_node.module in self.dependency_graph:
                            self.dependency_graph[ast_node.module].imported_by.add(
                                node.module_name
                            )

                        # Track specific imports
                        for name in ast_node.names:
                            if ast_node.level == 0:
                                full_import = f"{ast_node.module}.{name.name}"
                            else:
                                module_parts = node.module_name.split(".")
                                relative_path = module_parts[: -ast_node.level]
                                full_import = f"{'.'.join(relative_path)}.{name.name}"

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
            self._import_and_track_module(module_name)

    def _import_and_track_module(self, module_name: str) -> Optional[ModuleType]:
        try:
            module_parts = module_name.split(".")
            if len(module_parts) > 1:
                relative_path = Path(*module_parts[1:])
                module_path = self.package_path / relative_path.with_suffix(".py")
            else:
                module_path = self.package_path / "__init__.py"

            if not module_path.exists():
                return None

            # Create/update node first
            if module_name not in self.dependency_graph:
                node = DependencyNode(
                    module_name=module_name,
                    file_path=module_path,
                    last_modified=module_path.stat().st_mtime,
                )
                self.dependency_graph[module_name] = node
            else:
                node = self.dependency_graph[module_name]
                node.subclasses.clear()
                node.superclasses.clear()

            # Load module first
            module = importlib.import_module(module_name)
            self.module_cache[module_name] = module

            # Now track imports and inheritance
            self._track_imports(module_path, node)
            self._update_inheritance_relationships(module_name)

            return module

        except Exception as e:
            logger.error(f"Failed to import {module_name}: {e}", exc_info=True)
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

            for class_subclasses in node.subclasses.values():
                for subclass_name in class_subclasses:
                    for module_name, node in self.dependency_graph.items():
                        class_names = {
                            name
                            for name, _ in inspect.getmembers(
                                self.module_cache[module_name], inspect.isclass
                            )
                        }
                        if subclass_name in class_names:
                            if module_name not in affected:
                                affected.add(module_name)
                                to_process.add(module_name)

            for superclass_set in node.superclasses.values():
                for superclass in superclass_set:
                    if current != changed_module and changed_module not in affected:
                        affected.add(changed_module)
                        to_process.add(changed_module)

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
                for super_module in superclass_modules:
                    if super_module in modules:
                        visit(super_module)

            result.append(module_name)

        for module_name in modules:
            visit(module_name)

        return result

    def _preserve_state(self, old_module: ModuleType) -> None:
        module_name = old_module.__name__
        if module_name not in self.dependency_graph:
            return

        node = self.dependency_graph[module_name]
        for name, obj in inspect.getmembers(old_module):
            if hasattr(obj, "__dict__"):
                node.preserved_state[id(obj)] = dict(obj.__dict__)

    def _restore_state(self, old_module: ModuleType, new_module: ModuleType) -> None:
        module_name = new_module.__name__
        if module_name not in self.dependency_graph:
            return

        node = self.dependency_graph[module_name]
        for name, new_obj in inspect.getmembers(new_module):
            if hasattr(old_module, name):
                old_obj = getattr(old_module, name)

                if inspect.isclass(old_obj) and issubclass(old_obj, Enum):
                    for dependent_module_name in node.imported_by:
                        if dependent_module_name in sys.modules:
                            dependent_module = sys.modules[dependent_module_name]
                            if hasattr(dependent_module, name):
                                setattr(dependent_module, name, new_obj)
                    continue

                if id(old_obj) in node.preserved_state and hasattr(new_obj, "__dict__"):
                    for key, value in node.preserved_state[id(old_obj)].items():
                        if not key.startswith("__"):
                            setattr(new_obj, key, value)

    def reload_module(self, module_name: str) -> Tuple[bool, List[str]]:
        logger.debug(f"Reloading module: {module_name}")
        reloaded_modules = []
        try:
            if not self._import_and_track_module(module_name):
                return False, []

            affected = self._get_affected_modules(module_name)
            logger.debug(f"Affected modules: {affected}")
            sorted_modules = self._sort_modules_by_dependencies(affected)
            logger.debug(f"Sorted modules: {sorted_modules}")

            for mod_name in sorted_modules:
                if mod_name in sys.modules:
                    self._preserve_state(sys.modules[mod_name])

            for mod_name in sorted_modules:
                if mod_name not in sys.modules:
                    continue

                try:
                    old_module = sys.modules[mod_name]
                    del sys.modules[mod_name]

                    new_module = self._import_and_track_module(mod_name)
                    if not new_module:
                        logger.error(f"Failed to reimport {mod_name}")
                        return False, reloaded_modules

                    self._restore_state(old_module, new_module)
                    reloaded_modules.append(mod_name)

                except SyntaxError as e:
                    logger.error(f"Syntax error in {mod_name}: {e}")
                    return False, reloaded_modules

            return True, reloaded_modules

        except Exception as e:
            logger.error(f"Failed to reload {module_name}: {e}", exc_info=True)
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

    def _scan_package_structure(self) -> None:
        """Recursively scan the package directory to build initial dependency graph."""
        logger.debug(f"Starting deep package scan at {self.package_path}")

        def scan_directory(directory: Path) -> None:
            for item in directory.iterdir():
                if item.is_file() and item.suffix == ".py":
                    module_parts = (
                        item.relative_to(self.package_path).with_suffix("").parts
                    )
                    if item.name == "__init__.py":
                        if len(module_parts) > 0:
                            module_name = (
                                f"{self.root_package}.{'.'.join(module_parts[:-1])}"
                            )
                        else:
                            module_name = self.root_package
                    else:
                        module_name = f"{self.root_package}.{'.'.join(module_parts)}"

                    logger.debug(f"Found module: {module_name} at {item}")
                    self._import_and_track_module(module_name)

                elif (
                    item.is_dir()
                    and not item.name.startswith(".")
                    and not item.name == "__pycache__"
                ):
                    init_file = item / "__init__.py"
                    if init_file.exists():
                        scan_directory(item)

        scan_directory(self.package_path)
        self._build_inheritance_tree()

    def _build_inheritance_tree(self) -> None:
        """Build complete inheritance relationships after all modules are loaded."""
        for module_name, module in self.module_cache.items():
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if obj.__module__.startswith(self.root_package):
                    for base in obj.__bases__:
                        if base.__module__.startswith(self.root_package):
                            # Track subclass relationship
                            base_module = base.__module__
                            if base_module in self.dependency_graph:
                                if (
                                    base.__name__
                                    not in self.dependency_graph[base_module].subclasses
                                ):
                                    self.dependency_graph[base_module].subclasses[
                                        base.__name__
                                    ] = set()
                                self.dependency_graph[base_module].subclasses[
                                    base.__name__
                                ].add(obj.__name__)

                            # Track superclass relationship
                            if (
                                obj.__name__
                                not in self.dependency_graph[module_name].superclasses
                            ):
                                self.dependency_graph[module_name].superclasses[
                                    obj.__name__
                                ] = set()
                            self.dependency_graph[module_name].superclasses[
                                obj.__name__
                            ].add(base.__name__)
