import importlib
import sys
import textwrap
import time

import pytest

from mountaineer.hotreload import HotReloader, resolve_relative_import


@pytest.fixture
def test_package_dir(tmp_path, request):
    """Create test package structure with unique name per test."""
    test_name = request.node.name.replace("test_", "")
    pkg_name = f"test_package_{test_name}"
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


def test_initial_dependency_tracking(test_package_dir):
    """Test dependency tracking."""
    pkg_dir, pkg_name = test_package_dir
    # Import the modules
    importlib.import_module(f"{pkg_name}.base")
    importlib.import_module(f"{pkg_name}.child")
    # Initialize the HotReloader with entrypoint
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.child")

    child_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.child")
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")

    assert f"{pkg_name}.base" in child_deps["imports"]
    assert child_deps["superclasses"] == {"ChildClass": {"BaseClass"}}
    assert base_deps["subclasses"] == {"BaseClass": {"ChildClass"}}


def test_preserve_object_state(test_package_dir):
    """Test state preservation."""
    pkg_dir, pkg_name = test_package_dir
    # Import modules
    child_module = importlib.import_module(f"{pkg_name}.child")
    # Create object
    obj = child_module.ChildClass()
    obj.value = 30
    obj.child_value = 40

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.child")

    # Modify child.py
    (pkg_dir / "child.py").write_text(
        textwrap.dedent(
            f"""
        from {pkg_name}.base import BaseClass

        class ChildClass(BaseClass):
            def __init__(self):
                super().__init__()
                self.child_value = 20
            def get_modified_value(self):
                return self.child_value * 2
    """
        )
    )

    time.sleep(0.1)
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.child")
    assert success
    assert obj.value == 30
    assert obj.child_value == 40


def test_inheritance_changes(test_package_dir):
    """Test inheritance changes."""
    pkg_dir, pkg_name = test_package_dir

    # Import child first to establish initial inheritance
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

    time.sleep(0.1)
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.base")
    assert success

    # Verify both inheritance relationships
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")
    assert base_deps["subclasses"] == {"BaseClass": {"IntermediateClass", "ChildClass"}}

    # Verify child still works
    child_module = importlib.import_module(f"{pkg_name}.child")
    new_child = child_module.ChildClass()
    assert new_child.get_value() == 10


def test_cyclic_dependencies(test_package_dir):
    """Test cyclic dependencies."""
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

    # Import modules
    importlib.import_module(f"{pkg_name}.module_b")
    importlib.import_module(f"{pkg_name}.module_a")

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.module_a")

    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.module_a")
    assert success


def test_partial_reload_failure(test_package_dir):
    """Test partial reload failure."""
    pkg_dir, pkg_name = test_package_dir

    # Import base and child
    importlib.import_module(f"{pkg_name}.base")
    importlib.import_module(f"{pkg_name}.child")

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

    time.sleep(0.1)
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.child")
    assert not success

    # Verify base module is still functional
    base_module = importlib.import_module(f"{pkg_name}.base")
    obj = base_module.BaseClass()
    assert obj.get_value() == 10


def test_multiple_inheritance(test_package_dir):
    """Test multiple inheritance."""
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

    # Import necessary modules
    importlib.import_module(f"{pkg_name}.base")
    importlib.import_module(f"{pkg_name}.mixin")
    importlib.import_module(f"{pkg_name}.child")

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.child")

    time.sleep(0.1)
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.child")
    assert success

    child = importlib.import_module(f"{pkg_name}.child")
    obj = child.ChildClass()
    assert obj.get_value() == 10
    assert obj.log() == "logged"


def test_enum_reload(test_package_dir):
    """Test that enums are properly handled during reload."""
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

    # Import modules
    importlib.import_module(f"{pkg_name}.status")
    doc_module = importlib.import_module(f"{pkg_name}.document")

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

    time.sleep(0.1)
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.status")
    assert success

    # Verify new enum value is available
    status_module = importlib.import_module(f"{pkg_name}.status")
    assert hasattr(status_module.Status, "ARCHIVED")


def test_import_alias_dependency_graph(test_package_dir):
    """Test that the dependency graph correctly tracks imports with aliases."""
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
            print("Reloading main with mod import:", id(mod))
            print("Reloading value", mod.MyModel().get_value())

            def get_model_value():
                print("USING MOD", id(mod))
                model = mod.MyModel()
                return model.get_value()
            """
        )
    )

    # Import modules
    importlib.import_module(f"{pkg_name}.models")
    main_module = importlib.import_module(f"{pkg_name}.main")

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.main")

    # Ensure the dependency graph is built correctly
    main_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.main")
    assert (
        f"{pkg_name}.models" in main_deps["imports"]
    ), "models should be in main's imports"

    # Check that models knows it's imported by main
    models_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.models")
    assert (
        f"{pkg_name}.main" in models_deps["imported_by"]
    ), "main should be in models' imported_by"

    # Verify that the code works
    assert main_module.get_model_value() == 10

    # Modify models.py - note this file needs to change in a way that's significant
    # enough for the module refresher to actually reload the logic. Switching 10 -> 20
    # for instance (same amount of chars) is not enough for it to reload.
    (pkg_dir / "models.py").write_text(
        textwrap.dedent(
            """
            class MyModel:
                def get_value(self):
                    return 200
            """
        )
    )

    time.sleep(0.1)
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.models")
    assert success
    assert f"{pkg_name}.main" in reloaded

    # Verify that the updated value is reflected
    main_module = sys.modules[f"{pkg_name}.main"]
    print("GET VALUE", id(main_module))
    assert main_module.get_model_value() == 200


def test_relative_import(test_package_dir):
    """Test that the dependency graph correctly tracks imports with aliases."""
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
            print("Main module loaded with models id:", id(models))

            def get_model_value():
                print("get_model_value using models id:", id(models))
                model = models.MyModel()
                print("MyModel class id:", id(models.MyModel))
                return model.get_value()
            """
        )
    )

    # Import and verify initial state
    models_module = importlib.import_module(f"{pkg_name}.models")
    main_module = importlib.import_module(f"{pkg_name}.main")
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.main")

    # Verify initial dependency graph
    deps = hot_reloader.get_module_dependencies(f"{pkg_name}.models")
    print("DEPS", deps)
    assert (
        f"{pkg_name}.models.example" in deps["imports"]
    ), "models should import example"
    assert (
        f"{pkg_name}.main" in deps["imported_by"]
    ), "models should be imported by main"

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

    # Force file timestamp change
    time.sleep(0.1)

    # Reload and verify
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.models.example")
    assert success, "Reload should succeed"
    assert f"{pkg_name}.models.example" in reloaded, "example.py should be reloaded"
    assert f"{pkg_name}.models" in reloaded, "models/__init__.py should be reloaded"
    assert f"{pkg_name}.main" in reloaded, "main.py should be reloaded"

    # Verify the module was actually reloaded with new code
    new_value = main_module.get_model_value()
    assert new_value == 200, f"Expected 200, got {new_value}"


def test_ignores_irrelevant_files(test_package_dir):
    # TODO: Make this cleaner, more streamlined
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
            print("Main module loaded with models id:", id(models))

            def get_model_value():
                print("get_model_value using models id:", id(models))
                model = models.MyModel()
                print("MyModel class id:", id(models.MyModel))
                return model.get_value()
            """
        )
    )

    # Import and verify initial state
    models_module = importlib.import_module(f"{pkg_name}.models")
    main_module = importlib.import_module(f"{pkg_name}.main")
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.main")

    # Verify initial dependency graph
    deps = hot_reloader.get_module_dependencies(f"{pkg_name}.models")
    print("DEPS", deps)
    assert (
        f"{pkg_name}.models.example" in deps["imports"]
    ), "models should import example"
    assert (
        f"{pkg_name}.main" in deps["imported_by"]
    ), "models should be imported by main"

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

    # Force file timestamp change
    time.sleep(0.1)

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


def test_package_structure_scanning(test_package_dir):
    """Test package structure scanning with nested directories."""
    pkg_dir, pkg_name = test_package_dir

    # Create nested package structure
    nested_dir = pkg_dir / "nested"
    nested_dir.mkdir()
    (nested_dir / "__init__.py").write_text("")
    (nested_dir / "module.py").write_text(
        """
class NestedClass:
    pass
"""
    )

    sub_nested = nested_dir / "subnested"
    sub_nested.mkdir()
    (sub_nested / "__init__.py").write_text(
        """
class SubNestedInit:
    pass
"""
    )

    # Import modules
    importlib.import_module(f"{pkg_name}.nested")
    importlib.import_module(f"{pkg_name}.nested.module")
    importlib.import_module(f"{pkg_name}.nested.subnested")

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.nested")

    # Verify modules are tracked
    assert f"{pkg_name}.nested.module" in hot_reloader.dependency_graph
    assert f"{pkg_name}.nested" in hot_reloader.dependency_graph
    assert f"{pkg_name}.nested.subnested" in hot_reloader.dependency_graph


def test_inheritance_tree_building(test_package_dir):
    """Test inheritance tree building with complex inheritance."""
    pkg_dir, pkg_name = test_package_dir

    # Create a hierarchy of classes
    (pkg_dir / "base.py").write_text(
        """
class BaseClass:
    pass

class AnotherBase:
    pass
"""
    )

    (pkg_dir / "middle.py").write_text(
        f"""
from {pkg_name}.base import BaseClass, AnotherBase

class MiddleClass(BaseClass):
    pass

class MultipleInheritance(BaseClass, AnotherBase):
    pass
"""
    )

    (pkg_dir / "leaf.py").write_text(
        f"""
from {pkg_name}.middle import MiddleClass

class LeafClass(MiddleClass):
    pass
"""
    )

    # Import modules
    importlib.import_module(f"{pkg_name}.base")
    importlib.import_module(f"{pkg_name}.middle")
    importlib.import_module(f"{pkg_name}.leaf")

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.leaf")

    # Verify inheritance relationships
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")
    middle_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.middle")
    leaf_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.leaf")

    assert "MiddleClass" in base_deps["subclasses"]["BaseClass"]
    assert "MultipleInheritance" in base_deps["subclasses"]["BaseClass"]
    assert "MultipleInheritance" in base_deps["subclasses"]["AnotherBase"]
    assert "LeafClass" in middle_deps["subclasses"]["MiddleClass"]
    assert leaf_deps["superclasses"]["LeafClass"] == {"MiddleClass"}


def test_package_structure_excluded_dirs(test_package_dir):
    """Test that certain directories are excluded from scanning."""
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


def test_inheritance_tree_module_updates(test_package_dir):
    """Test inheritance tree updates when modules change."""
    pkg_dir, pkg_name = test_package_dir

    # Initial class structure
    (pkg_dir / "dynamic.py").write_text(
        f"""
from {pkg_name}.base import BaseClass

class DynamicClass(BaseClass):
    pass
"""
    )

    # Import modules
    importlib.import_module(f"{pkg_name}.base")
    importlib.import_module(f"{pkg_name}.dynamic")

    # Initialize HotReloader
    hot_reloader = HotReloader(pkg_name, pkg_dir, entrypoint=f"{pkg_name}.dynamic")

    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")
    assert "DynamicClass" in base_deps["subclasses"]["BaseClass"]

    # Update inheritance
    (pkg_dir / "dynamic.py").write_text(
        """
class DynamicClass:  # No longer inherits from BaseClass
    pass
"""
    )

    time.sleep(0.1)
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.dynamic")
    assert success

    # Verify inheritance is updated
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")
    assert "DynamicClass" not in base_deps["subclasses"].get("BaseClass", set())


@pytest.mark.parametrize(
    "root_package, module_name, relative_path, level, expected",
    [
        # Absolute imports (level=0)
        (
            "my_package",
            "my_package.module",
            "other_module",
            0,
            "my_package.other_module",
        ),
        (
            "my_package",
            "my_package.module",
            "my_package.submodule",
            0,
            "my_package.submodule",
        ),
        ("my_package", "my_package.module", "", 0, "my_package"),
        # Relative imports within a module
        ("my_package", "my_package.module", "", 1, "my_package.module"),
        (
            "my_package",
            "my_package.module",
            "submodule",
            1,
            "my_package.module.submodule",
        ),
        ("my_package", "my_package.module", "", 2, "my_package"),
        ("my_package", "my_package.module", "submodule", 2, "my_package.submodule"),
        (
            "my_package",
            "my_package.sub.module",
            "submodule",
            2,
            "my_package.sub.submodule",
        ),
        ("my_package", "my_package.sub.module", "submodule", 3, "my_package.submodule"),
        # Relative imports within a package (__init__.py)
        ("my_package", "my_package.__init__", "", 1, "my_package"),
        ("my_package", "my_package.__init__", "submodule", 1, "my_package.submodule"),
        ("my_package", "my_package.sub.__init__", "", 1, "my_package.sub"),
        ("my_package", "my_package.sub.__init__", "module", 1, "my_package.sub.module"),
        ("my_package", "my_package.sub.__init__", "module", 2, "my_package.module"),
        # Edge cases
        ("my_package", "my_package.module", "", 0, "my_package"),
        ("my_package", "my_package.module", "", 5, None),  # Invalid level
        ("my_package", "my_package.module", "submodule", -1, None),  # Invalid level
        # Relative imports from deeply nested modules
        # ("my_package", "my_package.a.b.c.module", "utils", 2, "my_package.a.b.utils"),
        # ("my_package", "my_package.a.b.c.module", "utils", 3, "my_package.a.utils"),
        # ("my_package", "my_package.a.b.c.module", "utils", 4, "my_package.utils"),
        # Relative imports from __init__.py in nested packages
        (
            "my_package",
            "my_package.a.b.c.__init__",
            "utils",
            1,
            "my_package.a.b.c.utils",
        ),
        ("my_package", "my_package.a.b.c.__init__", "utils", 2, "my_package.a.b.utils"),
        ("my_package", "my_package.a.b.c.__init__", "utils", 3, "my_package.a.utils"),
        # Importing from the root package
        ("my_package", "my_package.sub.module", "", 3, "my_package"),
        # Invalid cases
        ("my_package", "my_package.module", "submodule", 100, None),  # Level too high
        (
            "my_package",
            "my_package.module",
            "submodule",
            0,
            "my_package.submodule",
        ),  # Absolute import
        # Relative import with no relative_path
        ("my_package", "my_package.module", "", 1, "my_package.module"),
        ("my_package", "my_package.module", "", 2, "my_package"),
    ],
)
def test_resolve_relative_import(
    root_package, module_name, relative_path, level, expected
):
    result = resolve_relative_import(root_package, module_name, relative_path, level)
    assert (
        result == expected
    ), f"Failed for module {module_name}, path {relative_path}, level {level}"
