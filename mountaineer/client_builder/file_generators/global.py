
from mountaineer.client_builder.file_generators.base import CodeBlock, FileGeneratorBase
from dataclasses import dataclass
from datetime import date, datetime, time
from json import dumps as json_dumps
from types import NoneType
from typing import Any
from uuid import UUID

from graphlib import TopologicalSorter

from mountaineer.actions.fields import FunctionActionType
from mountaineer.client_builder.interface_builders.controller import ControllerInterface
from mountaineer.client_builder.interface_builders.enum import EnumInterface
from mountaineer.client_builder.interface_builders.model import ModelInterface
from mountaineer.client_builder.parser import (
    ActionWrapper,
    ControllerWrapper,
    EnumWrapper,
    FieldWrapper,
    ModelWrapper,
    SelfReference,
)
from mountaineer.client_builder.types import (
    DictOf,
    ListOf,
    LiteralOf,
    Or,
    SetOf,
    TupleOf,
    TypeDefinition,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath


class GlobalControllerGenerator(FileGeneratorBase):
    """
    Generate the root/controller.ts file for all global definitions.
    - Models
    - Enums
    - Controllers

    """
    def __init__(self, controller_wrappers: list[ControllerWrapper], managed_path: ManagedViewPath):
        super().__init__(managed_path)
        self.controller_wrappers = controller_wrappers

    def script(self):
        # Recursively traverse our controller definitions, which themselves point to other
        # in-memory objects that should be converted like models and enums
        controllers = self._gather_all_controllers(self.controller_wrappers)
        models, enums = self._gather_models_and_enums(controllers)

        # Resolve the MRO ordering for all the interfaces, since they'll be defined
        # in one file
        controller_sorted = self._build_controller_graph(controllers)
        model_enum_sorted = self._build_model_enum_graph(models, enums)

        yield CodeBlock(
            "/*",
            " * Models + Enums",
            " */",
        )

        # Models and enums will be used by the action signatures contained
        # in the controllers
        for item in model_enum_sorted:
            if isinstance(item, ModelWrapper):
                yield CodeBlock(ModelInterface.from_model(item).to_js())
            elif isinstance(item, EnumWrapper):
                yield CodeBlock(EnumInterface.from_enum(item).to_js())
            else:
                raise ValueError(f"Unsupported item type: {item}")

        yield CodeBlock(
            "/*",
            " * View Controllers",
            " */",
        )

        # Then process controllers in dependency order
        for controller in controller_sorted:
            yield CodeBlock(ControllerInterface.from_controller(controller).to_js())

    def _build_model_enum_graph(
        self, models: list[ModelWrapper], enums: list[EnumWrapper]
    ):
        """Build dependency graph for models and enums"""
        # Build id-based graph
        graph: dict[int, set[int]] = {}
        id_to_obj: dict[int, ModelWrapper | EnumWrapper] = {}

        # Initialize graph entries for all models and enums
        for model in models:
            graph[id(model)] = set()
            id_to_obj[id(model)] = model

        for enum in enums:
            graph[id(enum)] = set()
            id_to_obj[id(enum)] = enum

        # Add model superclass dependencies
        for model in models:
            graph[id(model)].update(id(superclass) for superclass in model.superclasses)

            # Add field dependencies
            for field in model.value_models:
                if isinstance(field.value, (ModelWrapper, EnumWrapper)):
                    graph[id(model)].add(id(field.value))

        # Convert graph to use actual objects for TopologicalSorter
        sorted_ids = TopologicalSorter(graph).static_order()
        return [id_to_obj[node_id] for node_id in sorted_ids]

    def _build_controller_graph(
        self, controllers: list[ControllerWrapper]
    ) -> list[ControllerWrapper]:
        """Build dependency graph for controllers"""
        # Build id-based graph
        graph: dict[int, set[int]] = {}
        id_to_obj: dict[int, ControllerWrapper] = {}

        # Initialize graph entries for all controllers
        for controller in controllers:
            graph[id(controller)] = set()
            id_to_obj[id(controller)] = controller

        # Add controller superclass dependencies
        for controller in controllers:
            graph[id(controller)].update(
                id(superclass) for superclass in controller.superclasses
            )

        # Convert graph to use actual objects for TopologicalSorter
        sorted_ids = TopologicalSorter(graph).static_order()
        return [id_to_obj[node_id] for node_id in sorted_ids]

    def _gather_all_controllers(
        self, controllers: list[ControllerWrapper]
    ) -> list[ControllerWrapper]:
        """Gather all controllers including superclasses"""
        seen_ids = set()
        result = []

        def gather(controller: ControllerWrapper) -> None:
            if id(controller) not in seen_ids:
                seen_ids.add(id(controller))
                for superclass in controller.superclasses:
                    gather(superclass)
                result.append(controller)

        for controller in controllers:
            gather(controller)

        return result

    def _gather_models_and_enums(
        self, controllers: list[ControllerWrapper]
    ) -> tuple[list[ModelWrapper], list[EnumWrapper]]:
        """Collect all unique models and enums from controllers"""
        models_dict: dict[int, ModelWrapper] = {}
        enums_dict: dict[int, EnumWrapper] = {}

        def process_value(value):
            if isinstance(value, ModelWrapper):
                process_model(value)
            elif isinstance(value, EnumWrapper):
                enums_dict[id(value)] = value
            elif isinstance(value, TypeDefinition):
                for child in value.children:
                    process_value(child)
            else:
                LOGGER.info(f"Non-complex value: {value}")

        def process_model(model: ModelWrapper) -> None:
            """Process a model and all its dependencies"""
            if id(model) not in models_dict:
                models_dict[id(model)] = model
                # Process all fields
                for field in model.value_models:
                    process_value(field.value)
                # Process superclasses
                for superclass in model.superclasses:
                    process_model(superclass)

        # Process all models from controllers
        for controller in controllers:
            if controller.render:
                process_model(controller.render)
            for action in controller.actions.values():
                if action.request_body:
                    process_model(action.request_body)
                if action.response_body:
                    process_model(action.response_body)

        return list(models_dict.values()), list(enums_dict.values())
