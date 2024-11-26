import importlib
import sys
import textwrap
from pathlib import Path

import pytest

from mountaineer.hotreload import HotReloader, resolve_relative_import


@pytest.fixture
def test_package_dir(tmp_path: Path, request):
    """
    Create test package structure with unique name per test so we allow
    client functions to modify their files without adverse affects on other tests.

    """
    test_name = request.node.name.replace("test_", "")
    pkg_name = f"test_package_{test_name}".replace("[", "_").replace("]", "_")

    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir()

    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "base.py").write_text(
        textwrap.dedent(
            """
        class BaseClass:
            def __init__(self):
                self.value = 10
            def get_value(self):
                return self.value
    """
        )
    )

    (pkg_dir / "child.py").write_text(
        textwrap.dedent(
            f"""
        from {pkg_name}.base import BaseClass

        class ChildClass(BaseClass):
            def __init__(self):
                super().__init__()
                self.child_value = 20
            def get_child_value(self):
                return self.child_value
    """
        )
    )

    # Make it immediately importable
    sys.path.insert(0, str(pkg_dir.parent))
    sys.path.insert(0, str(pkg_dir))

    return pkg_dir, pkg_name


def test_initial_dependency_tracking(test_package_dir: tuple[Path, str]):
    """
    Test initial dependency tracking on load.

    """
    pkg_dir, pkg_name = test_package_dir

    # Initialize the HotReloader with entrypoint, this should take
    # care of loading the child+base files
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.child")

    child_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.child")
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")

    assert child_deps
    assert base_deps

    assert f"{pkg_name}.base" in child_deps.imports
    assert child_deps.superclasses == {"ChildClass": {"BaseClass"}}
    assert base_deps.subclasses == {"BaseClass": {"ChildClass"}}


def test_inheritance_changes(test_package_dir: tuple[Path, str]):
    """
    Test inheritance changes if the base model is changed.

    """
    pkg_dir, pkg_name = test_package_dir

    # Verify initial class logic
    child_module = importlib.import_module(f"{pkg_name}.child")
    initial_child = child_module.ChildClass()
    assert initial_child.get_value() == 10

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.child")

    # Modify base with new intermediate class
    (pkg_dir / "base.py").write_text(
        textwrap.dedent(
            """
        class BaseClass:
            def __init__(self):
                self.value = 10
            def get_value(self):
                return self.value
        class IntermediateClass(BaseClass):
            def get_intermediate_value(self):
                return 15
    """
        )
    )

    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.base")
    assert success

    # Verify both inheritance relationships
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")
    assert base_deps
    assert base_deps.subclasses == {"BaseClass": {"IntermediateClass", "ChildClass"}}

    # Verify child still works
    child_module = importlib.import_module(f"{pkg_name}.child")
    new_child = child_module.ChildClass()
    assert new_child.get_value() == 10


def test_cyclic_dependencies(test_package_dir: tuple[Path, str]):
    """
    Test cyclic dependencies.

    """
    pkg_dir, pkg_name = test_package_dir

    # Write module files
    (pkg_dir / "module_b.py").write_text(
        textwrap.dedent(
            """
        class B:
            def __init__(self):
                self.value = 10
    """
        )
    )
    (pkg_dir / "module_a.py").write_text(
        textwrap.dedent(
            f"""
        from {pkg_name}.module_b import B
        class A:
            def __init__(self):
                self.b = B()
    """
        )
    )

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.module_a")

    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.module_a")
    assert success


def test_partial_reload_failure(test_package_dir: tuple[Path, str]):
    """
    Test partial reload failure.

    """
    pkg_dir, pkg_name = test_package_dir

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.child")

    # Introduce syntax error in child.py
    (pkg_dir / "child.py").write_text(
        textwrap.dedent(
            f"""
        from {pkg_name}.base import BaseClass

        class ChildClass(BaseClass)  # Syntax error
            def get_child_value(self):
                return 20
    """
        )
    )

    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.child")
    assert not success

    # Verify base module is still functional
    base_module = importlib.import_module(f"{pkg_name}.base")
    obj = base_module.BaseClass()
    assert obj.get_value() == 10


def test_multiple_inheritance(test_package_dir: tuple[Path, str]):
    """
    Test multiple inheritance.

    """
    pkg_dir, pkg_name = test_package_dir

    # Write mixin.py
    (pkg_dir / "mixin.py").write_text(
        textwrap.dedent(
            """
        class LoggerMixin:
            def log(self):
                return "logged"
    """
        )
    )

    # Update child.py to use multiple inheritance
    (pkg_dir / "child.py").write_text(
        textwrap.dedent(
            f"""
        from {pkg_name}.base import BaseClass
        from {pkg_name}.mixin import LoggerMixin

        class ChildClass(BaseClass, LoggerMixin):
            def get_child_value(self):
                return 20
    """
        )
    )

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.child")

    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.child")
    assert success

    child = importlib.import_module(f"{pkg_name}.child")
    obj = child.ChildClass()
    assert obj.get_value() == 10
    assert obj.log() == "logged"


def test_enum_reload(test_package_dir: tuple[Path, str]):
    """
    Test that enums are properly handled during reload.

    """
    pkg_dir, pkg_name = test_package_dir

    # Create initial enum file
    (pkg_dir / "status.py").write_text(
        textwrap.dedent(
            """
            from enum import Enum

            class Status(Enum):
                DRAFT = "draft"
                PUBLISHED = "published"
            """
        )
    )

    # Create a file that uses the enum
    (pkg_dir / "document.py").write_text(
        textwrap.dedent(
            f"""
            from {pkg_name}.status import Status

            class Document:
                def __init__(self):
                    self.status = Status.DRAFT

                def get_status(self):
                    return self.status
            """
        )
    )

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.document")

    # Modify enum file - add new status
    (pkg_dir / "status.py").write_text(
        textwrap.dedent(
            """
            from enum import Enum

            class Status(Enum):
                DRAFT = "draft"
                PUBLISHED = "published"
                ARCHIVED = "archived"
            """
        )
    )

    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.status")
    assert success

    # Verify new enum value is available
    status_module = importlib.import_module(f"{pkg_name}.status")
    assert hasattr(status_module.Status, "ARCHIVED")


def test_import_alias_dependency_graph(test_package_dir: tuple[Path, str]):
    """
    Test that the dependency graph correctly tracks imports with aliases.

    """
    pkg_dir, pkg_name = test_package_dir

    # Create models.py with initial class
    (pkg_dir / "models.py").write_text(
        textwrap.dedent(
            """
            class MyModel:
                def get_value(self):
                    return 10
            """
        )
    )

    # Create main.py that imports models using an alias
    (pkg_dir / "main.py").write_text(
        textwrap.dedent(
            f"""
            import {pkg_name}.models as mod

            def get_model_value():
                model = mod.MyModel()
                return model.get_value()
            """
        )
    )

    # Import modules
    main_module = importlib.import_module(f"{pkg_name}.main")

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.main")

    # Ensure the dependency graph is built correctly
    main_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.main")
    assert main_deps
    assert (
        f"{pkg_name}.models" in main_deps.imports
    ), "models should be in main's imports"

    # Check that models knows it's imported by main
    models_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.models")
    assert models_deps
    assert (
        f"{pkg_name}.main" in models_deps.imported_by
    ), "main should be in models' imported_by"

    # Verify that the code works
    assert main_module.get_model_value() == 10

    (pkg_dir / "models.py").write_text(
        textwrap.dedent(
            """
            class MyModel:
                def get_value(self):
                    return 20
            """
        )
    )

    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.models")
    assert success
    assert f"{pkg_name}.main" in reloaded

    # Verify that the updated value is reflected
    main_module = sys.modules[f"{pkg_name}.main"]
    assert main_module.get_model_value() == 20


def test_relative_import(test_package_dir: tuple[Path, str]):
    """
    Test that the dependency graph correctly tracks imports with aliases.

    """
    pkg_dir, pkg_name = test_package_dir

    # Create the package structure
    (pkg_dir / "models").mkdir()
    (pkg_dir / "models/example.py").write_text(
        textwrap.dedent(
            """
            class MyModel:
                def get_value(self):
                    return 10
            """
        )
    )
    (pkg_dir / "models/__init__.py").write_text(
        textwrap.dedent(
            """
            from .example import MyModel as MyModel
            """
        )
    )
    (pkg_dir / "main.py").write_text(
        textwrap.dedent(
            f"""
            from {pkg_name} import models

            def get_model_value():
                model = models.MyModel()
                return model.get_value()
            """
        )
    )

    # Import and verify initial state
    main_module = importlib.import_module(f"{pkg_name}.main")
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.main")

    # Verify initial dependency graph
    deps = hot_reloader.get_module_dependencies(f"{pkg_name}.models")
    assert deps
    assert f"{pkg_name}.models.example" in deps.imports, "models should import example"
    assert f"{pkg_name}.main" in deps.imported_by, "models should be imported by main"

    # Verify initial functionality
    initial_value = main_module.get_model_value()
    assert initial_value == 10, f"Expected 10, got {initial_value}"

    # Modify the model
    (pkg_dir / "models/example.py").write_text(
        textwrap.dedent(
            """
            class MyModel:
                def get_value(self):
                    return 200
            """
        )
    )

    # Reload and verify
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.models.example")
    assert success, "Reload should succeed"
    assert f"{pkg_name}.models.example" in reloaded, "example.py should be reloaded"
    assert f"{pkg_name}.models" in reloaded, "models/__init__.py should be reloaded"
    assert f"{pkg_name}.main" in reloaded, "main.py should be reloaded"

    # Verify the module was actually reloaded with new code
    new_value = main_module.get_model_value()
    assert new_value == 200, f"Expected 200, got {new_value}"


def test_ignores_irrelevant_files(test_package_dir: tuple[Path, str]):
    """
    Ignores files that aren't directly in the DAG path of the original file

    """
    pkg_dir, pkg_name = test_package_dir

    # Create the package structure
    (pkg_dir / "models").mkdir()
    (pkg_dir / "models/example.py").write_text(
        textwrap.dedent(
            f"""
            from {pkg_name}.other_item import OtherFile
            class MyModel:
                def get_value(self):
                    return 10
            """
        )
    )
    (pkg_dir / "models/__init__.py").write_text(
        textwrap.dedent(
            """
            from .example import MyModel as MyModel
            """
        )
    )
    (pkg_dir / "other_item.py").write_text(
        textwrap.dedent(
            """
            class OtherFile:
                pass
            """
        )
    )
    (pkg_dir / "main.py").write_text(
        textwrap.dedent(
            f"""
            from {pkg_name} import models
            from {pkg_name}.other_item import OtherFile

            def get_model_value():
                model = models.MyModel()
                return model.get_value()
            """
        )
    )

    # Import and verify initial state
    main_module = importlib.import_module(f"{pkg_name}.main")
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.main")

    # Verify initial dependency graph
    deps = hot_reloader.get_module_dependencies(f"{pkg_name}.models")
    assert deps
    assert f"{pkg_name}.models.example" in deps.imports, "models should import example"
    assert f"{pkg_name}.main" in deps.imported_by, "models should be imported by main"

    # Verify initial functionality
    initial_value = main_module.get_model_value()
    assert initial_value == 10, f"Expected 10, got {initial_value}"

    # Modify the model
    (pkg_dir / "models/example.py").write_text(
        textwrap.dedent(
            """
            class MyModel:
                def get_value(self):
                    return 200
            """
        )
    )

    # Reload and verify
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.models.example")
    assert success, "Reload should succeed"
    assert f"{pkg_name}.models.example" in reloaded, "example.py should be reloaded"
    assert f"{pkg_name}.models" in reloaded, "models/__init__.py should be reloaded"
    assert f"{pkg_name}.main" in reloaded, "main.py should be reloaded"
    assert (
        f"{pkg_name}.other_item" not in reloaded
    ), "other_item.py should not be reloaded"

    # Verify the module was actually reloaded with new code
    new_value = main_module.get_model_value()
    assert new_value == 200, f"Expected 200, got {new_value}"


def test_package_structure_scanning(test_package_dir: tuple[Path, str]):
    """
    Test package structure scanning with nested directories.

    """
    pkg_dir, pkg_name = test_package_dir

    # Create nested package structure
    nested_dir = pkg_dir / "nested"
    nested_dir.mkdir()
    (nested_dir / "__init__.py").write_text("")
    (nested_dir / "module.py").write_text(
        textwrap.dedent(
            """
            class NestedClass:
                pass
            """
        )
    )

    sub_nested = nested_dir / "subnested"
    sub_nested.mkdir()
    (sub_nested / "__init__.py").write_text(
        textwrap.dedent(
            """
            class SubNestedInit:
                pass
            """
        )
    )

    importlib.import_module(f"{pkg_name}.nested")
    importlib.import_module(f"{pkg_name}.nested.module")
    importlib.import_module(f"{pkg_name}.nested.subnested")

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.nested")

    # Verify modules are tracked
    assert f"{pkg_name}.nested.module" in hot_reloader.dependency_graph
    assert f"{pkg_name}.nested" in hot_reloader.dependency_graph
    assert f"{pkg_name}.nested.subnested" in hot_reloader.dependency_graph


def test_inheritance_tree_building(test_package_dir: tuple[Path, str]):
    """
    Test inheritance tree building with complex inheritance.

    """
    pkg_dir, pkg_name = test_package_dir

    # Create a hierarchy of classes
    (pkg_dir / "base.py").write_text(
        textwrap.dedent(
            """
            class BaseClass:
                pass

            class AnotherBase:
                pass
            """
        )
    )

    (pkg_dir / "middle.py").write_text(
        textwrap.dedent(
            f"""
            from {pkg_name}.base import BaseClass, AnotherBase

            class MiddleClass(BaseClass):
                pass

            class MultipleInheritance(BaseClass, AnotherBase):
                pass
            """
        )
    )

    (pkg_dir / "leaf.py").write_text(
        textwrap.dedent(
            f"""
            from {pkg_name}.middle import MiddleClass

            class LeafClass(MiddleClass):
                pass
            """
        )
    )

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.leaf")

    # Verify inheritance relationships
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")
    middle_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.middle")
    leaf_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.leaf")

    assert base_deps
    assert middle_deps
    assert leaf_deps

    assert "MiddleClass" in base_deps.subclasses["BaseClass"]
    assert "MultipleInheritance" in base_deps.subclasses["BaseClass"]
    assert "MultipleInheritance" in base_deps.subclasses["AnotherBase"]
    assert "LeafClass" in middle_deps.subclasses["MiddleClass"]
    assert leaf_deps.superclasses["LeafClass"] == {"MiddleClass"}


def test_package_structure_excluded_dirs(test_package_dir: tuple[Path, str]):
    """
    Test that certain directories are excluded from scanning.

    """
    pkg_dir, pkg_name = test_package_dir

    # Create directories that should be excluded
    hidden_dir = pkg_dir / ".hidden"
    hidden_dir.mkdir()
    (hidden_dir / "module.py").write_text("class Hidden: pass")

    pycache_dir = pkg_dir / "__pycache__"
    pycache_dir.mkdir(exist_ok=True)
    (pycache_dir / "cached.py").write_text("class Cached: pass")

    # Import modules (only the ones we expect to include)
    importlib.import_module(f"{pkg_name}.base")

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.base")

    # Verify excluded modules aren't tracked
    for module in hot_reloader.dependency_graph:
        assert not module.endswith("Hidden")
        assert not module.endswith("Cached")


def test_inheritance_tree_module_updates(test_package_dir: tuple[Path, str]):
    """Test inheritance tree updates when modules change."""
    pkg_dir, pkg_name = test_package_dir

    # Initial class structure
    (pkg_dir / "dynamic.py").write_text(
        textwrap.dedent(
            f"""
            from {pkg_name}.base import BaseClass

            class DynamicClass(BaseClass):
                pass
            """
        )
    )

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.dynamic")

    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")
    assert base_deps
    assert "DynamicClass" in base_deps.subclasses["BaseClass"]

    # Update inheritance
    (pkg_dir / "dynamic.py").write_text(
        textwrap.dedent(
            """
            class DynamicClass:  # No longer inherits from BaseClass
                pass
            """
        )
    )

    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.dynamic")
    assert success

    # Verify inheritance is updated
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")
    assert base_deps
    assert "DynamicClass" not in base_deps.subclasses.get("BaseClass", set())


@pytest.mark.xfail(strict=False)
def test_new_file_reload(test_package_dir: tuple[Path, str]):
    """
    Test adding and reloading a new file that imports other modules.

    TODO: We need to investigate why this is unreliable in remote CI but reliable locally.

    """
    pkg_dir, pkg_name = test_package_dir

    # Import initial modules
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.base")

    # Create new file that imports base
    (pkg_dir / "new_module.py").write_text(
        textwrap.dedent(
            f"""
            from {pkg_name}.base import BaseClass

            class NewClass(BaseClass):
                def get_special_value(self):
                    return self.get_value() * 2
            """
        )
    )

    print("All files", list(pkg_dir.iterdir()), sys.path)  # noqa: T201

    # Calling this should also start tracking the new file
    new_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.new_module")
    assert new_deps

    # Verify we have also updated the old file bidirectionally
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")
    assert base_deps

    assert f"{pkg_name}.base" in new_deps.imports
    assert new_deps.superclasses == {"NewClass": {"BaseClass"}}
    assert "NewClass" in base_deps.subclasses["BaseClass"]

    # Verify that the new module was reloaded
    new_module = sys.modules[f"{pkg_name}.new_module"]
    obj = new_module.NewClass()
    assert obj.get_special_value() == 20

    # Modify the base module
    (pkg_dir / "base.py").write_text(
        textwrap.dedent(
            """
            class BaseClass:
                def __init__(self):
                    self.value = 20
                def get_value(self):
                    return self.value
            """
        )
    )

    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.base")
    assert success
    assert reloaded == [f"{pkg_name}.base", f"{pkg_name}.new_module"]

    # Verify that the new module was reloaded
    new_module = sys.modules[f"{pkg_name}.new_module"]
    obj = new_module.NewClass()
    assert obj.get_special_value() == 40


#
# absolute imports
#


def parse_relative_import(import_str: str) -> tuple[str, int]:
    """
    Parse a relative import string into (import_path, level).

    Examples:
        "module" -> ("module", 0)
        ".module" -> ("module", 1)
        "..module" -> ("module", 2)
        "..." -> ("", 3)

    """
    level = 0
    for char in import_str:
        if char == ".":
            level += 1
        else:
            break
    return import_str[level:], level


@pytest.mark.parametrize(
    "current_module, from_import_str, import_name, sys_modules, expected",
    [
        # Absolute imports (no dots)
        (
            "my_package.module",
            "other_module",
            "MyClass",
            {"my_package.module.other_module", "my_package.other_module"},
            "my_package.module.other_module",
        ),
        (
            "my_package.module",
            "my_package.submodule",
            "MyClass",
            {"my_package.submodule"},
            "my_package.submodule",
        ),
        # Single dot relative imports (current directory)
        (
            "my_package.module",
            ".submodule",
            "MyClass",
            {"my_package.module.submodule"},
            "my_package.module.submodule",
        ),
        (
            "my_package.__init__",
            ".submodule",
            "MyClass",
            {"my_package.submodule"},
            "my_package.submodule",
        ),
        # Two dot relative imports (parent directory)
        (
            "my_package.sub.module",
            "..other_module",
            "MyClass",
            {"my_package.sub.other_module"},
            "my_package.sub.other_module",
        ),
        (
            "my_package.sub.module",
            "..other_package.module",
            "MyClass",
            {"my_package.sub.other_package.module"},
            "my_package.sub.other_package.module",
        ),
        # Three or more dot relative imports
        (
            "my_package.a.b.c.module",
            "...utils",
            "MyClass",
            {"my_package.a.b.utils"},
            "my_package.a.b.utils",
        ),
        (
            "my_package.deep.nested.module",
            "....top_level",
            "MyClass",
            {"my_package.top_level"},
            "my_package.top_level",
        ),
        # Empty imports (importing the package itself)
        (
            "my_package.module",
            ".",
            "MyClass",
            {"my_package.module"},
            "my_package.module",
        ),
        (
            "my_package.sub.module",
            "..",
            "MyClass",
            {"my_package.sub"},
            "my_package.sub",
        ),
        (
            "my_package.a.b.module",
            "...",
            "MyClass",
            {"my_package.a"},
            "my_package.a",
        ),
        # Edge and error cases
        (
            "my_package.module",
            ".....",  # Too many dots
            "MyClass",
            set(),
            None,
        ),
        (
            "my_package.module",
            "nonexistent_module",
            "MyClass",
            set(),
            None,
        ),
        (
            "my_package.module",
            "my_package.nonexistent",
            "MyClass",
            set(),
            None,
        ),
    ],
)
def test_resolve_relative_import(
    current_module: str,
    from_import_str: str,
    import_name: str,
    sys_modules: set[str],
    expected: str | None,
):
    from_import, level = parse_relative_import(from_import_str)

    result = resolve_relative_import(
        root_package="my_package",
        current_module=current_module,
        from_import=from_import,
        from_import_level=level,
        import_name=import_name,
        sys_modules=sys_modules,
    )

    assert result == expected, (
        f"Failed for import '{from_import_str}' in module '{current_module}'\n"
        f"Expected: {expected}\n"
        f"Got: {result}"
    )
