from enum import Enum
from dataclasses import dataclass

class TimeoutMeasureType(Enum):
    CPU_TIME = "CPU_TIME"
    WALL_TIME = "WALL_TIME"


class TimeoutType(Enum):
    """
    Soft is just within the thread itself, assumes that the active task is able to
    give up control of the async loop.
    Hard is a hard timeout, that will kill the task (ie. recycle the process) if it's
    not able to give up control.
    """

    SOFT = "SOFT"
    HARD = "HARD"


@dataclass
class TimeoutDefinition:
    measurement: TimeoutMeasureType
    timeout_type: TimeoutType
    timeout_seconds: float
