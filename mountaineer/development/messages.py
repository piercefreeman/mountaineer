from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

TResponse = TypeVar("TResponse")


@dataclass
class IsolatedMessageBase(Generic[TResponse]):
    """Base class for all messages passed between main process and isolated app context"""

    pass


@dataclass
class ErrorResponse:
    """Generic error response"""

    exception: str
    traceback: str


@dataclass
class SuccessResponse:
    """Generic success response"""

    pass


@dataclass
class BootupMessage(IsolatedMessageBase[SuccessResponse | ErrorResponse]):
    """Message to bootup the isolated app context"""

    pass


@dataclass
class BuildJsMessage(IsolatedMessageBase[SuccessResponse | ErrorResponse]):
    """Message to trigger JS compilation"""

    updated_js: list[Path] | None


@dataclass
class BuildUseServerMessage(IsolatedMessageBase[SuccessResponse | ErrorResponse]):
    """Message to build the useServer support files"""

    pass
