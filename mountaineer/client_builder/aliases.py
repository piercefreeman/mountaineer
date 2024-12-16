from collections import Counter
from typing import Sequence, Type

from inflection import camelize
from pydantic import BaseModel

from mountaineer.client_builder.parser import (
    ControllerParser,
    ControllerWrapper,
    CoreWrapper,
    ModelWrapper,
)
from mountaineer.client_builder.typescript import normalize_interface


class AliasManager:
    """
    Since Python classes are implicitly isolated by {module}.{name} we can have
    multiple definitions with the same class name within our runtime. In our
    generated TypeScript this is not available to us because we use one
    consolidated file to implement the ground truth interfaces.

    While we could automatically prefix each definition with the module, this gets
    to be quite long and cumbersome. Instead, we can use this alias manager
    to detect conflicts and resolve them by renaming the conflicting definitions.

    """

    def assign_global_names(self, parser: ControllerParser):
        """
        Assign globally unique names to potentially duplicate models, enums, controllers, etc

        """
        reference_counts: Counter[str] = Counter()

        # Each of these dictionaries are keyed with the actual classes in memory themselves, so
        # any values should be unique representations of different logical classes
        for self_reference in parser.parsed_self_references:
            self_reference.name = normalize_interface(self_reference.name)
            # No need to update the reference counts, since we expect these to just
            # point to an existing model anyway

        parsed_groups: Sequence[Sequence[CoreWrapper]] = [
            list(parser.parsed_models.values()),
            list(parser.parsed_enums.values()),
            list(parser.parsed_exceptions.values()),
            list(parser.parsed_controllers.values()),
        ]

        for parsed_group in parsed_groups:
            for parsed_wrapper in parsed_group:
                parsed_wrapper.name.global_name = normalize_interface(
                    parsed_wrapper.name.global_name
                )
                reference_counts.update([parsed_wrapper.name.global_name])

        # Any reference counts that have more than one reference need to be uniquified
        duplicate_names = {
            name for name, count in reference_counts.items() if count > 1
        }

        converted_models: dict[Type[BaseModel], str] = {}

        # Models must be updated before the self references
        for parsed_group in parsed_groups:
            for parsed_wrapper in parsed_group:
                if parsed_wrapper.name.global_name in duplicate_names:
                    prefix = self._typescript_prefix_from_module(
                        parsed_wrapper.module_name
                    )
                    parsed_wrapper.name.global_name = (
                        f"{prefix}_{parsed_wrapper.name.global_name}"
                    )

                    if isinstance(parsed_wrapper, ModelWrapper):
                        converted_models[
                            parsed_wrapper.model
                        ] = parsed_wrapper.name.global_name

        # Only once we update the models should we update the self references to the
        # new values - otherwise the lookup map will be empty
        for self_reference in parser.parsed_self_references:
            if self_reference.model in converted_models:
                self_reference.name = converted_models[self_reference.model]

    def assign_local_names(self, parser: ControllerParser):
        """
        Whereas our global logic has to deal with the possibility of multiple classes with
        the same name across the project, typically there's only one definition of a class
        that's imported into a single controller file. This method will assign unique "local names"
        as a shortcut to make it easier for clients to reference these classes.

        """
        for controller in parser.parsed_controllers.values():
            # This should mirror the same logic that the LocalModelGenerator uses to populate
            # the models.ts file that's tied to each controller
            controllers = ControllerWrapper.get_all_embedded_controllers([controller])
            embedded_types = ControllerWrapper.get_all_embedded_types(
                [controller], include_superclasses=True
            )

            reference_counter: Counter[str] = Counter()

            parsed_groups: Sequence[Sequence[CoreWrapper]] = [
                controllers,
                embedded_types.models,
                embedded_types.enums,
                embedded_types.exceptions,
            ]

            for parsed_group in parsed_groups:
                for parsed_wrapper in parsed_group:
                    parsed_wrapper.name.local_name = normalize_interface(
                        parsed_wrapper.name.local_name
                    )
                    reference_counter.update([parsed_wrapper.name.local_name])

            duplicate_names = {
                name for name, count in reference_counter.items() if count > 1
            }

            for parsed_group in parsed_groups:
                for parsed_wrapper in parsed_group:
                    if parsed_wrapper.name.local_name in duplicate_names:
                        prefix = self._typescript_prefix_from_module(
                            parsed_wrapper.module_name
                        )
                        parsed_wrapper.name.local_name = (
                            f"{prefix}_{parsed_wrapper.name.local_name}"
                        )

    def _typescript_prefix_from_module(self, module: str):
        module_parts = module.split(".")
        module_parts = [module.strip("_") for module in module_parts]
        return "".join([camelize(component) for component in module_parts])
