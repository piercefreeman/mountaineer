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

    def assign_unique_names(self, parser: ControllerParser):
        """
        Assign unique names to potentially duplicate models, enums, controllers, etc

        """
        reference_counts = Counter()

        # Each of these dictionaries are keyed with the actual classes in memory themselves, so
        # any values should be unique representations of different logical classes
        for model in self.parser.parsed_models.values():
            model.name = normalize_interface(model.name)
            reference_counts.update([model.name])
        for self_reference in self.parser.parsed_self_references:
            self_reference.name = normalize_interface(self_reference.name)
            # No need to update the reference counts, since we expect these to just
            # point to an existing model anyway
        for enum in self.parser.parsed_enums.values():
            enum.name = normalize_interface(enum.name)
            reference_counts.update([enum.name])
        for controller in self.parser.parsed_controllers.values():
            controller.name = normalize_interface(controller.name)
            reference_counts.update([controller.name])

        # Any reference counts that have more than one reference need to be uniquified
        duplicate_names = {
            name for name, count in reference_counts.items() if count > 1
        }

        converted_models: dict[Type[BaseModel], str] = {}

        for model in self.parser.parsed_models.values():
            if model.name in duplicate_names:
                prefix = self._typescript_prefix_from_module(model.model.__module__)
                model.name = f"{prefix}_{model.name}"
                converted_models[model.model] = model.name
        for self_reference in self.parser.parsed_self_references:
            if self_reference.model in converted_models:
                self_reference.name = converted_models[self_reference.model]
        for enum in self.parser.parsed_enums.values():
            if enum.name in duplicate_names:
                prefix = self._typescript_prefix_from_module(enum.enum.__module__)
                enum.name = f"{prefix}_{enum.name}"
        for controller in self.parser.parsed_controllers.values():
            if controller.name in duplicate_names:
                prefix = self._typescript_prefix_from_module(
                    controller.controller.__module__
                )
                controller.name = f"{prefix}_{controller.name}"
