from typing import Any, Sequence, Type

from graphlib import TopologicalSorter

from mountaineer.generics import get_typevar_mapping
from mountaineer.migrations.actions import (
    DatabaseActions,
)
from mountaineer.migrations.db_stubs import DBObject, DBObjectPointer
from mountaineer.migrations.generics import (
    is_type_compatible,
)
from mountaineer.migrations.handlers import (
    DelegateContext,
    HandlerBase,
    HandlerBaseMeta,
    N,
)


class DatabaseMemorySerializer:
    """
    Serialize the in-memory database representations into a format that can be
    compared to the database definitions on disk.

    """

    def __init__(self):
        self.handlers: dict[Any, HandlerBase] = {}

        # Construct the directed acyclic graph of the in-memory database objects
        # that indicate what order items should be fulfilled in
        self.db_dag = []

        # Import the items from the registry
        if not HandlerBaseMeta.get_registry():
            raise ValueError("No handlers registered")
        for handler_cls in HandlerBaseMeta.get_registry():
            self.register_handler(handler_cls)

    def register_handler(self, handler: Type["HandlerBase"]):
        # When we initialize an instance of the handler the base model should
        # take care of extracting the (from, to) typehint from the typed generic
        handler_instance = handler(self)

        # TODO: Refactor this into the common mountaineer package when this code
        # makes it to the main codebase
        mapping = get_typevar_mapping(handler)
        if N not in mapping:
            raise ValueError(
                f"Handler {handler} must have type hints for previous and next"
            )

        next = mapping[N]
        if next in self.handlers:
            raise ValueError(f"Handler for type {next} already registered")

        self.handlers[next] = handler_instance

    def delegate(
        self,
        next: Any,
        context: DelegateContext | None,
        dependent_on: list[DBObject | DBObjectPointer] | None = None,
    ):
        """
        Find the most specific relevant handler. For instance, if a subclass
        is a registered handler, we should use that instead of the superclass
        If multiple are found we throw, since we can't determine which one to use
        for the resolution.

        """
        # Filter and find all handlers that can handle the types of previous and next, considering inheritance
        raw_candidates: list[tuple[Type, HandlerBase, float]] = []
        for registered_next, handler in self.handlers.items():
            type_priority = is_type_compatible(next, registered_next)
            if type_priority < float("inf"):
                raw_candidates.append((registered_next, handler, type_priority))

        # If no candidates found, we might raise an error or handle this case differently
        if not raw_candidates:
            raise ValueError(
                f"No suitable handler found for types: {next} {type(next)} (context: {context})"
            )

        best_match_priority = min([priority for _, _, priority in raw_candidates])
        candidates = [
            (registered_next, handler)
            for registered_next, handler, priority in raw_candidates
            if priority == best_match_priority
        ]

        # If multiple candidates are the most specific equally, we have ambiguity
        if len(candidates) > 1:
            raise ValueError(
                f"Ambiguous handlers for types: {next} {type(next)} (context: {context})\n"
                + "\n".join([str(candidate) for candidate in candidates])
            )

        # Use the most specific handler (first in the sorted list)
        _, handler = candidates[0]

        for result, dependencies in list(
            handler.convert(
                next,
                context=context if context is not None else DelegateContext(),
            )
        ):
            yield result, dependencies + (dependent_on or [])

    def order_db_objects(
        self,
        db_objects: Sequence[tuple[DBObject, Sequence[DBObject | DBObjectPointer]]],
    ):
        """
        Resolve the order that the database objects should be created
        or modified.

        """
        # First, go through and create a representative object for each of
        # the representation names
        db_objects_by_name: dict[str, DBObject] = {}
        for db_object, _ in db_objects:
            # Only perform this mapping for objects that are not pointers
            if isinstance(db_object, DBObjectPointer):
                continue

            # If the object is already in the dictionary, make sure the values
            # are equal. Otherwise this indicates that there is a conflicting
            # name with a different definition which we don't allow
            if db_object.representation() in db_objects_by_name:
                ground_truth_obj = db_objects_by_name[db_object.representation()]
                if ground_truth_obj != db_object:
                    raise ValueError(
                        f"Conflicting definitions for {db_object.representation()}\n{ground_truth_obj} != {db_object}"
                    )
            db_objects_by_name[db_object.representation()] = db_object

        # Make sure all the pointers can be resolved by full objects
        # Otherwise we want a verbose error that gives more context
        for _, dependencies in db_objects:
            for dep in dependencies:
                if isinstance(dep, DBObjectPointer):
                    if dep.representation() not in db_objects_by_name:
                        raise ValueError(
                            f"Pointer {dep.representation()} not found in the defined database objects"
                        )

        # Map the potentially different objects to the same object
        graph_edges = {
            db_objects_by_name[obj.representation()]: [
                db_objects_by_name[dep.representation()] for dep in dependencies
            ]
            for obj, dependencies in db_objects
        }

        # Construct the directed acyclic graph
        ts = TopologicalSorter(graph_edges)
        return {obj: i for i, obj in enumerate(ts.static_order())}

    async def build_actions(
        self,
        actor: DatabaseActions,
        previous: list[DBObject],
        previous_ordering: dict[DBObject, int],
        next: list[DBObject],
        next_ordering: dict[DBObject, int],
    ):
        # Arrange each object by their representation so we can determine
        # the state of each
        previous_by_name = {obj.representation(): obj for obj in previous}
        next_by_name = {obj.representation(): obj for obj in next}

        # Sort the objects by the order that they should be created in
        if set(next_ordering.keys()) != set(next):
            raise ValueError(
                "Ordering next dictionary keys must be the same as the objects in the list"
            )
        if set(previous_ordering.keys()) != set(previous):
            raise ValueError(
                "Ordering previous dictionary keys must be the same as the objects in the list"
            )

        previous = sorted(previous, key=lambda obj: previous_ordering[obj])
        next = sorted(next, key=lambda obj: next_ordering[obj])

        for next_obj in next:
            previous_obj = previous_by_name.get(next_obj.representation())

            if previous_obj is None and next_obj is not None:
                await next_obj.create(actor)
            elif previous_obj is not None and next_obj is not None:
                # Only migrate if they're actually different
                if previous_obj != next_obj:
                    await next_obj.migrate(previous_obj, actor)

        # For all of the items that were in the previous state but not in the
        # next state, we should delete them
        to_delete = [
            previous_obj
            for previous_obj in previous
            if previous_obj.representation() not in next_by_name
        ]
        # We use the reversed representation to destroy objects with more dependencies
        # before the dependencies themselves
        to_delete.reverse()
        for previous_obj in to_delete:
            await previous_obj.destroy(actor)

        return actor.dry_run_actions
