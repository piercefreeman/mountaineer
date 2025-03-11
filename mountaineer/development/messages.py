import asyncio
import uuid
from asyncio import Future
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from multiprocessing import Queue
from pathlib import Path
from queue import Empty
from typing import Any, Generic, TypeVar
from mountaineer.io import get_free_port
import secrets
from threading import Thread
from multiprocessing.managers import BaseManager
from contextlib import contextmanager

from mountaineer.logging import LOGGER

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


