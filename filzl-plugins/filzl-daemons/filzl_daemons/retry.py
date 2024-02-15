from datetime import datetime, timedelta
from random import random

from pydantic import BaseModel

from filzl_daemons.models import DaemonAction


class RetryPolicy(BaseModel):
    # The maximum number of attempts to make before giving up
    # If max_attempts is set to None, will retry indefinitely
    max_attempts: int | None = None

    # Initial backoff delay in seconds before the first retry. Subsequent retries
    # will use this value adjusted by the backoff factor and jitter.
    backoff_seconds: int = 1

    # Factor by which the backoff delay is multiplicatively increased after each attempt.
    backoff_factor: float = 2.0

    # Jitter is used to add randomness to the backoff delay. This is a fraction of
    # the backoff delay that will be randomly added or subtracted to each delay.
    # Setting jitter to 0 disables it. A common default is 0.1 (10% of the backoff delay).
    jitter: float = 0.1


def retry_is_allowed(daemon_action: DaemonAction) -> bool:
    """
    Determines if there are any remaining attempts for the given daemon action.
    """
    if daemon_action.retry_max_attempts is None:
        return True
    return daemon_action.retry_current_attempt < daemon_action.retry_max_attempts


def calculate_retry(
    daemon_action: DaemonAction,
) -> datetime:
    """
    Given the current state of a daemon action and the retry policy, determine the
    datetime at which the next retry should be attempted.

    """
    ended_datetime = daemon_action.ended_datetime or datetime.now()

    # Calculate the backoff delay
    backoff_seconds = daemon_action.retry_backoff_seconds
    backoff_factor = daemon_action.retry_backoff_factor
    jitter = daemon_action.retry_jitter

    # Calculate delay with exponential backoff
    delay = backoff_seconds * (backoff_factor**daemon_action.retry_current_attempt)

    # Apply jitter by adjusting the delay by a random percentage of the jitter factor
    jitter_delta = (
        delay * jitter * (random() * 2 - 1)
    )  # random.random() * 2 - 1 gives a range of -1 to 1
    delay_with_jitter = max(0, delay + jitter_delta)  # Ensure delay isn't negative

    # Determine the datetime for the next retry
    next_retry_datetime = ended_datetime + timedelta(seconds=delay_with_jitter)

    return next_retry_datetime
