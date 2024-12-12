@dataclass
class ActionInterface(InterfaceBase):
    name: str
    parameters: str
    typehints: str
    default_parameters: str | None
    response_type: str
    body: str
    required_models: list[str]

    def to_js(self) -> str:
        script = f"export const {self.name} = ({self.parameters} : {self.typehints}"
        if self.default_parameters:
            script += f" = {self.default_parameters}"
        script += f"): {self.response_type} => {{ {self.body} }}"
        return script

    def from_action(self, action: ActionWrapper):
        pass
