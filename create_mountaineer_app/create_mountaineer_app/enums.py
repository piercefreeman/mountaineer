from dataclasses import dataclass
from enum import Enum


class PackageManager(str, Enum):
    UV = "uv"
    POETRY = "poetry"
    VENV = "venv"


@dataclass
class EditorDescription:
    name: str
    path: str | None


class EditorType(Enum):
    VSCODE = EditorDescription(name="vscode", path="vscode")
    VIM = EditorDescription(name="vim", path="vim")
    ZED = EditorDescription(name="zed", path=None)

    @classmethod
    def from_name(cls, name: str) -> "EditorType":
        for editor in cls:
            if editor.value.name == name:
                return editor
        raise ValueError(f"Invalid editor type: {name}")
