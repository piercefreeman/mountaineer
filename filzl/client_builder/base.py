from abc import ABC, abstractmethod
from pathlib import Path


class ClientBuilderBase(ABC):
    @abstractmethod
    def handle_file(self, view_root_path: Path, current_path: Path):
        pass
