from datetime import datetime, timezone

import pytest

from filzl_daemons.models import DaemonAction
from filzl_daemons.retry import calculate_retry


@pytest.mark.parametrize(
    "current_attempt, backoff_seconds, backoff_factor, expected_delay",
    [
        (0, 1, 2, 1),  # First attempt, should result in base backoff seconds
        (1, 1, 2, 2),  # Second attempt, should double
        (2, 1, 2, 4),  # Third attempt, should double again
        (3, 2, 2, 16),  # Fourth attempt with a base of 2 seconds
        (0, 3, 3, 3),  # First attempt with different base and factor
    ],
)
def test_determine_retry_without_jitter(
    current_attempt, backoff_seconds, backoff_factor, expected_delay
):
    daemon_action = DaemonAction(
        workflow_name="test_workflow",
        instance_id=1,
        state="",
        registry_id="",
        input_body="",
        retry_current_attempt=current_attempt,
        ended_datetime=datetime.now(timezone.utc),
        retry_backoff_seconds=backoff_seconds,
        retry_backoff_factor=backoff_factor,
        retry_jitter=0,
    )
    assert daemon_action.ended_datetime

    next_retry_datetime = calculate_retry(daemon_action)
    actual_delay = (next_retry_datetime - daemon_action.ended_datetime).total_seconds()

    assert actual_delay == expected_delay


@pytest.mark.parametrize(
    "current_attempt, backoff_seconds, backoff_factor, jitter, min_delay, max_delay",
    [
        (1, 1, 2, 0.1, 1.8, 2.2),  # Second attempt, slight jitter
        (2, 1, 2, 0.2, 3.2, 4.8),  # Third attempt, more noticeable jitter
    ],
)
def test_determine_retry_with_jitter(
    current_attempt, backoff_seconds, backoff_factor, jitter, min_delay, max_delay
):
    daemon_action = DaemonAction(
        workflow_name="test_workflow",
        instance_id=1,
        state="",
        registry_id="",
        input_body="",
        retry_current_attempt=current_attempt,
        ended_datetime=datetime.now(timezone.utc),
        retry_backoff_seconds=backoff_seconds,
        retry_backoff_factor=backoff_factor,
        retry_jitter=jitter,
    )
    assert daemon_action.ended_datetime

    next_retry_datetime = calculate_retry(daemon_action)
    actual_delay = (next_retry_datetime - daemon_action.ended_datetime).total_seconds()

    assert min_delay <= actual_delay <= max_delay
