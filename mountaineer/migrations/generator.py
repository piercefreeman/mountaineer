from collections import defaultdict
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from inspect import ismodule
from json import dumps as json_dumps
from time import time
from types import ModuleType
from typing import Any, Callable, Type

from pydantic import BaseModel

from mountaineer import Depends
from mountaineer.migrations.actions import DatabaseActions, DryRunAction, DryRunComment
from mountaineer.migrations.db_memory_serializer import DatabaseMemorySerializer
from mountaineer.migrations.db_stubs import DBObject, DBObjectPointer
from mountaineer.migrations.dependency import MigrationDependencies
from mountaineer.migrations.migration import MigrationRevisionBase
from mountaineer.migrations.migrator import Migrator

MIGRATION_TEMPLATE = """
{header_imports}

class MigrationRevision(MigrationRevisionBase):
    \"""
    Migration auto-generated on {timestamp}.

    Context: {user_message}

    \"""
    up_revision: str = {rev}
    down_revision: str | None = {prev_rev}

    async def up(
        self,
        migrator: Migrator = Depends(MigrationDependencies.get_migrator),
    ):
{up_code}

    async def down(
        self,
        migrator: Migrator = Depends(MigrationDependencies.get_migrator),
    ):
{down_code}
"""


class MigrationGenerator:
    """
    Generate the physical python files that will be used to migrate the database.

    """

    def __init__(self):
        self.import_tracker: defaultdict[str, set[str]] = defaultdict(set)
        self.serializer = DatabaseMemorySerializer()

    async def new_migration(
        self,
        down_objects_with_dependencies: list[
            tuple[DBObject, list[DBObject | DBObjectPointer]]
        ],
        up_objects_with_dependencies: list[
            tuple[DBObject, list[DBObject | DBObjectPointer]]
        ],
        down_revision: str | None,
        user_message: str | None,
    ) -> tuple[str, str]:
        self.import_tracker.clear()
        revision = str(int(time()))

        # Import requirements for every file. We need to explicitly provide the location
        # to the dependencies, since this is a synthetic module and not an actual class where
        # we can track the module.
        self.track_import(Migrator)
        self.track_import(MigrationRevisionBase)
        self.track_import(
            MigrationDependencies,
            explicit="mountaineer.migrations.dependency.MigrationDependencies",
        )
        self.track_import(Depends)

        next_objects = [obj for obj, _ in up_objects_with_dependencies]
        previous_objects = [obj for obj, _ in down_objects_with_dependencies]

        next_objects_ordering = self.serializer.order_db_objects(
            up_objects_with_dependencies
        )
        previous_objects_ordering = self.serializer.order_db_objects(
            down_objects_with_dependencies
        )

        # Convert the SQLModels to their respective DBObjects, with dependencies
        up_actor = DatabaseActions()
        up_actions = await self.serializer.build_actions(
            up_actor,
            previous_objects,
            previous_objects_ordering,
            next_objects,
            next_objects_ordering,
        )
        up_code = self.actions_to_code(up_actions)

        down_actor = DatabaseActions()
        down_actions = await self.serializer.build_actions(
            down_actor,
            next_objects,
            next_objects_ordering,
            previous_objects,
            previous_objects_ordering,
        )
        down_code = self.actions_to_code(down_actions)

        imports: list[str] = []
        for module, classes in self.import_tracker.items():
            if classes:
                classes_list = ", ".join(sorted(classes))
                imports.append(f"from {module} import {classes_list}")

        code = MIGRATION_TEMPLATE.strip().format(
            migrator_import=DatabaseMemorySerializer.__module__,
            rev=json_dumps(revision),
            prev_rev=json_dumps(down_revision) if down_revision else "None",
            up_code=self.indent_code(up_code, 2),
            down_code=self.indent_code(down_code, 2),
            header_imports="\n".join(imports),
            timestamp=datetime.now().isoformat(),
            user_message=user_message or "None",
        )

        return code, revision

    def actions_to_code(self, actions: list[DryRunAction | DryRunComment]):
        code_lines: list[str] = []

        for action in actions:
            if isinstance(action, DryRunAction):
                # All the actions should be callables attached to the migrator
                migrator_signature = action.fn.__name__

                # Format the kwargs as python native types since the code has to be executable
                kwargs = ", ".join(
                    [f"{k}={self.format_arg(v)}" for k, v in action.kwargs.items()]
                )

                # Format the dependencies
                code_lines.append(
                    f"await migrator.actor.{migrator_signature}({kwargs})"
                )
            elif isinstance(action, DryRunComment):
                comment_lines = action.text.split("\n")
                for line in comment_lines:
                    code_lines.append(f"# {line}")
            else:
                raise ValueError(f"Unknown action type: {action}")

        if not code_lines:
            code_lines.append("pass")

        return code_lines

    def format_arg(self, value: Any) -> str:
        """
        Format the argument to be a valid Python code string, handle escaping of strings,
        and track necessary imports.

        """
        if isinstance(value, Enum):
            self.track_import(value.__class__)
            class_name = value.__class__.__name__
            return f"{class_name}.{value.name}"
        elif isinstance(value, bool):
            return "True" if value else "False"
        elif isinstance(value, (str, int, float)):
            # JSON dumps is used here for proper string escaping
            return json_dumps(value)
        elif isinstance(value, list):
            return f"[{', '.join([self.format_arg(v) for v in value])}]"
        elif isinstance(value, frozenset):
            # Sorting values isn't necessary for client code, but useful for test stability over time
            return f"frozenset({{{', '.join([self.format_arg(v) for v in sorted(value)])}}})"
        elif isinstance(value, set):
            return f"{{{', '.join([self.format_arg(v) for v in sorted(value)])}}}"
        elif isinstance(value, tuple):
            tuple_values = f"{', '.join([self.format_arg(v) for v in value])}"
            if len(value) == 1:
                # Trailing comma is necessary for single element tuples
                return f"({tuple_values},)"
            else:
                return f"({tuple_values})"
        elif isinstance(value, dict):
            return (
                "{"
                + ", ".join(
                    [
                        f"{self.format_arg(k)}: {self.format_arg(v)}"
                        for k, v in value.items()
                    ]
                )
                + "}"
            )
        elif isinstance(value, BaseModel) or is_dataclass(value):
            if isinstance(value, BaseModel):
                model_dict = value.model_dump()
            elif is_dataclass(value) and not isinstance(value, type):
                # Currently incorrect typehinting in pyright for isinstance(value, type)
                # Still results in a type[DataclassInstance] possible type. This can remove
                # the following 3 type ignores when fixed.
                # https://github.com/microsoft/pyright/issues/8963
                model_dict = asdict(value)  # type: ignore
            else:
                raise TypeError(
                    "Value must be a BaseModel instance or a dataclass instance."
                )

            self.track_import(value.__class__)  # type: ignore

            code = f"{value.__class__.__name__}("  # type: ignore
            code += ", ".join(
                [
                    f"{k}={self.format_arg(v)}"
                    for k, v in model_dict.items()
                    if v is not None
                ]
            )
            code += ")"
            return code
        elif value is None:
            return "None"
        else:
            raise ValueError(f"Unknown argument type: {value} ({type(value)})")

    def track_import(
        self,
        value: Type[Any] | Callable | ModuleType,
        explicit: str | None = None,
    ):
        if ismodule(value):
            # We require an explicit import for modules
            if not explicit:
                raise ValueError("Explicit import required for modules")

        if explicit:
            module, class_name = explicit.rsplit(".", 1)
        else:
            module = value.__module__
            class_name = value.__name__

        self.import_tracker[module].add(class_name)

    def indent_code(self, code: list[str], indent: int) -> str:
        return "\n".join([f"{' ' * 4 * indent}{line}" for line in code])
