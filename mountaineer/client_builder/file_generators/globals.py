from typing import Any

from graphlib import TopologicalSorter
from inflection import camelize

from mountaineer.client_builder.file_generators.base import (
    CodeBlock,
    FileGeneratorBase,
    ParsedController,
)
from mountaineer.client_builder.interface_builders.controller import ControllerInterface
from mountaineer.client_builder.interface_builders.enum import EnumInterface
from mountaineer.client_builder.interface_builders.exception import ExceptionInterface
from mountaineer.client_builder.interface_builders.model import ModelInterface
from mountaineer.client_builder.parser import (
    ControllerWrapper,
    EnumWrapper,
    ModelWrapper,
)
from mountaineer.client_builder.typescript import (
    TSLiteral,
    python_payload_to_typescript,
)
from mountaineer.paths import ManagedViewPath, generate_relative_import


class GlobalControllerGenerator(FileGeneratorBase):
    """
    Generate the root/controller.ts file for all global definitions.
    - Models
    - Enums
    - Controllers

    """

    def __init__(
        self,
        *,
        controller_wrappers: list[ControllerWrapper],
        managed_path: ManagedViewPath,
    ):
        super().__init__(managed_path=managed_path)
        self.controller_wrappers = controller_wrappers

    def script(self):
        # Recursively traverse our controller definitions, which themselves point to other
        # in-memory objects that should be converted like models and enums
        controllers = ControllerWrapper.get_all_embedded_controllers(
            self.controller_wrappers
        )
        embedded_types = ControllerWrapper.get_all_embedded_types(
            controllers, include_superclasses=True
        )

        # Resolve the MRO ordering for all the interfaces, since they'll be defined
        # in one file
        controller_sorted = self._build_controller_graph(controllers)
        model_enum_sorted = self._build_model_enum_graph(
            embedded_types.models, embedded_types.enums
        )

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
            " * Exceptions",
            " */",
        )

        # Exceptions don't have other dependencies so they can be added in any order
        for exception in embedded_types.exceptions:
            yield CodeBlock(ExceptionInterface.from_exception(exception).to_js())

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


class GlobalLinkGenerator(FileGeneratorBase):
    def __init__(
        self,
        *,
        parsed_controllers: list[ParsedController],
        managed_path: ManagedViewPath,
    ):
        super().__init__(managed_path=managed_path)
        self.parsed_controllers = parsed_controllers

    def script(self):
        """Generate global link aggregator"""
        imports: list[str] = []
        link_setters: dict[str, Any] = {}

        for parsed_controller in self.parsed_controllers:
            if parsed_controller.is_layout:
                continue

            controller_dir = parsed_controller.view_path.get_managed_code_dir()
            controller_implementation_path = generate_relative_import(
                self.managed_path, controller_dir / "links.ts"
            )

            # Add import and setter for this controller
            local_name = f"{parsed_controller.wrapper.name.global_name}GetLinks"
            imports.append(
                f"import {{ getLink as {local_name} }} from '{controller_implementation_path}';"
            )
            link_setters[
                # @pierce: 12-11-2024: Mirror the lowercase camelcase convention of previous versions
                TSLiteral(
                    camelize(
                        parsed_controller.wrapper.controller.__name__,
                        uppercase_first_letter=False,
                    )
                )
            ] = TSLiteral(local_name)

        link_generator = python_payload_to_typescript(link_setters)

        yield CodeBlock(*imports)
        yield CodeBlock(f"const linkGenerator = {link_generator};")
        yield CodeBlock("export default linkGenerator;")
