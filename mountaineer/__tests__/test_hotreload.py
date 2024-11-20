import importlib
import textwrap
import time

import pytest

from mountaineer.hotreload import HotReloader


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

    return pkg_dir, pkg_name


@pytest.fixture
def hot_reloader(test_package_dir):
    """Initialize hot reloader with unique package."""
    pkg_dir, pkg_name = test_package_dir
    return HotReloader(pkg_name, pkg_dir)


def test_initial_dependency_tracking(hot_reloader, test_package_dir):
    """Test dependency tracking."""
    pkg_dir, pkg_name = test_package_dir
    importlib.import_module(f"{pkg_name}.child")
    child_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.child")
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")

    assert f"{pkg_name}.base" in child_deps["imports"]
    assert child_deps["superclasses"] == {"ChildClass": {"BaseClass"}}
    assert base_deps["subclasses"] == {"BaseClass": {"ChildClass"}}


def test_preserve_object_state(hot_reloader, test_package_dir):
    """Test state preservation."""
    pkg_dir, pkg_name = test_package_dir
    child_module = importlib.import_module(f"{pkg_name}.child")
    obj = child_module.ChildClass()
    obj.value = 30
    obj.child_value = 40

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


def test_inheritance_changes(hot_reloader, test_package_dir):
    """Test inheritance changes."""
    pkg_dir, pkg_name = test_package_dir

    # Import child first to establish initial inheritance
    child_module = importlib.import_module(f"{pkg_name}.child")
    initial_child = child_module.ChildClass()
    assert initial_child.get_value() == 10

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


def test_cyclic_dependencies(hot_reloader, test_package_dir):
    """Test cyclic dependencies."""
    pkg_dir, pkg_name = test_package_dir
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

    (pkg_dir / "module_b.py").write_text(
        textwrap.dedent(
            """
        class B:
            def __init__(self):
                self.value = 10
    """
        )
    )

    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.module_a")
    assert success


# def test_detecting_changes(hot_reloader, test_package_dir):
#     """Test change detection."""
#     pkg_dir, pkg_name = test_package_dir
#     orig_content = (pkg_dir / "base.py").read_text()

#     (pkg_dir / "base.py").write_text(textwrap.dedent("""
#         class BaseClass:
#             def get_value(self):
#                 return 20
#     """))

#     time.sleep(0.1)
#     hot_reloader._import_and_track_module(f"{pkg_name}.base")  # Ensure module is tracked
#     changed = hot_reloader.check_for_changes()
#     assert f"{pkg_name}.base" in changed


def test_partial_reload_failure(hot_reloader, test_package_dir):
    """Test partial reload failure."""
    pkg_dir, pkg_name = test_package_dir
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

    base = importlib.import_module(f"{pkg_name}.base")
    obj = base.BaseClass()
    assert obj.get_value() == 10


def test_multiple_inheritance(hot_reloader, test_package_dir):
    """Test multiple inheritance."""
    pkg_dir, pkg_name = test_package_dir
    (pkg_dir / "mixin.py").write_text(
        textwrap.dedent(
            """
        class LoggerMixin:
            def log(self):
                return "logged"
    """
        )
    )

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

    importlib.import_module(f"{pkg_name}.mixin")
    time.sleep(0.1)
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.child")
    assert success

    child = importlib.import_module(f"{pkg_name}.child")
    obj = child.ChildClass()
    assert obj.get_value() == 10
    assert obj.log() == "logged"


def test_enum_reload(hot_reloader, test_package_dir):
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

    # Import and create instance
    doc_module = importlib.import_module(f"{pkg_name}.document")
    doc = doc_module.Document()
    assert doc.status == doc_module.Status.DRAFT

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

    # Try to reload the module
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.status")
    assert success

    # Verify original instance maintains its enum value
    assert doc.status == doc_module.Status.DRAFT

    # Verify new enum value is available
    status_module = importlib.import_module(f"{pkg_name}.status")
    assert hasattr(status_module.Status, "ARCHIVED")


def test_import_alias_reload(hot_reloader, test_package_dir):
    """Test reloading when using import aliases."""
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

    # Create main.py that imports from models
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

    # Import and ensure both modules are tracked
    main_module = importlib.import_module(f"{pkg_name}.main")
    hot_reloader._import_and_track_module(f"{pkg_name}.main")
    hot_reloader._import_and_track_module(f"{pkg_name}.models")

    assert main_module.get_model_value() == 10
    print("Dependencies:", hot_reloader.get_module_dependencies(f"{pkg_name}.models"))

    # Modify models.py
    (pkg_dir / "models.py").write_text(
        textwrap.dedent(
            """
            class MyModel:
                def get_value(self):
                    return 20
            """
        )
    )

    time.sleep(0.1)
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.models")
    assert success
    assert f"{pkg_name}.main" in reloaded

def test_package_structure_scanning(hot_reloader, test_package_dir):
    """Test package structure scanning with nested directories."""
    pkg_dir, pkg_name = test_package_dir

    # Create nested package structure
    nested_dir = pkg_dir / "nested"
    nested_dir.mkdir()
    (nested_dir / "__init__.py").write_text("")
    (nested_dir / "module.py").write_text("""
class NestedClass:
    pass
""")

    sub_nested = nested_dir / "subnested"
    sub_nested.mkdir()
    (sub_nested / "__init__.py").write_text("""
class SubNestedInit:
    pass
""")

    # Force rescan
    hot_reloader._scan_package_structure()

    # Verify modules are tracked
    assert f"{pkg_name}.nested.module" in hot_reloader.dependency_graph
    assert f"{pkg_name}.nested" in hot_reloader.dependency_graph
    assert f"{pkg_name}.nested.subnested" in hot_reloader.dependency_graph

def test_inheritance_tree_building(hot_reloader, test_package_dir):
    """Test inheritance tree building with complex inheritance."""
    pkg_dir, pkg_name = test_package_dir

    # Create a hierarchy of classes
    (pkg_dir / "base.py").write_text("""
class BaseClass:
    pass

class AnotherBase:
    pass
""")

    (pkg_dir / "middle.py").write_text(f"""
from {pkg_name}.base import BaseClass, AnotherBase

class MiddleClass(BaseClass):
    pass

class MultipleInheritance(BaseClass, AnotherBase):
    pass
""")

    (pkg_dir / "leaf.py").write_text(f"""
from {pkg_name}.middle import MiddleClass

class LeafClass(MiddleClass):
    pass
""")

    hot_reloader._scan_package_structure()

    # Verify inheritance relationships
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")
    middle_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.middle")
    leaf_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.leaf")

    assert "MiddleClass" in base_deps["subclasses"]["BaseClass"]
    assert "MultipleInheritance" in base_deps["subclasses"]["BaseClass"]
    assert "MultipleInheritance" in base_deps["subclasses"]["AnotherBase"]
    assert "LeafClass" in middle_deps["subclasses"]["MiddleClass"]
    assert leaf_deps["superclasses"]["LeafClass"] == {"MiddleClass"}

def test_package_structure_excluded_dirs(hot_reloader, test_package_dir):
    """Test that certain directories are excluded from scanning."""
    pkg_dir, pkg_name = test_package_dir

    # Create directories that should be excluded
    (pkg_dir / ".hidden").mkdir()
    (pkg_dir / ".hidden" / "module.py").write_text("class Hidden: pass")

    (pkg_dir / "__pycache__").mkdir()
    (pkg_dir / "__pycache__" / "cached.py").write_text("class Cached: pass")

    hot_reloader._scan_package_structure()

    # Verify excluded modules aren't tracked
    for module in hot_reloader.dependency_graph:
        assert not module.endswith("Hidden")
        assert not module.endswith("Cached")

def test_inheritance_tree_module_updates(hot_reloader, test_package_dir):
    """Test inheritance tree updates when modules change."""
    pkg_dir, pkg_name = test_package_dir

    # Initial class structure
    (pkg_dir / "dynamic.py").write_text(f"""
from {pkg_name}.base import BaseClass

class DynamicClass(BaseClass):
    pass
""")

    hot_reloader._scan_package_structure()
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")
    assert "DynamicClass" in base_deps["subclasses"]["BaseClass"]

    # Update inheritance
    (pkg_dir / "dynamic.py").write_text("""
class DynamicClass:  # No longer inherits from BaseClass
    pass
""")

    time.sleep(0.1)
    success, reloaded = hot_reloader.reload_module(f"{pkg_name}.dynamic")
    assert success

    # Verify inheritance is updated
    base_deps = hot_reloader.get_module_dependencies(f"{pkg_name}.base")
    assert "DynamicClass" not in base_deps["subclasses"].get("BaseClass", set())
