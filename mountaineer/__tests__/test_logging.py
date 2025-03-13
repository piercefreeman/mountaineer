import json
import logging
import os
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO

import pytest

from mountaineer.logging import debug_log_artifact, reset_artifact_dir, setup_logger


@contextmanager
def capture_logger_output(logger_func, *args, **kwargs):
    new_stdout, new_stderr = StringIO(), StringIO()
    with redirect_stdout(new_stdout), redirect_stderr(new_stderr):
        logger = logger_func(*args, **kwargs)
        yield logger, new_stdout, new_stderr


def test_setup_logger_name_and_level():
    logger_name = "test_logger"
    log_level = logging.DEBUG
    with capture_logger_output(setup_logger, logger_name, log_level) as (logger, _, _):
        assert logger.name == logger_name
        assert logger.level == log_level


def test_log_message_output():
    log_message = "Test message"
    logger_name = "output_logger"
    with capture_logger_output(setup_logger, logger_name) as (logger, stdout, _):
        logger.info(log_message)
        output = stdout.getvalue()
    # Since actual output includes ANSI escape codes for colors, we validate the presence of the message and level
    assert log_message in output
    assert "INFO" in output


def test_timestamp():
    logger_name = "format_logger"
    with capture_logger_output(setup_logger, logger_name) as (logger, stdout, _):
        logger.warning("Warning test")
        output = stdout.getvalue()
    log_output = json.loads(output.strip())
    assert "timestamp" in log_output


def test_exception_logging():
    logger_name = "exception_logger"
    with capture_logger_output(setup_logger, logger_name) as (logger, stdout, _):
        try:
            raise ValueError("Test exception")
        except ValueError:
            logger.exception("This is an exception")
        output = stdout.getvalue()
        log_output = json.loads(output.strip())
        assert "exception" in log_output
        assert "Test exception" in log_output["exception"]


@contextmanager
def modify_log_level(log_level: str):
    current_log_level = os.environ.get("MOUNTAINEER_LOG_LEVEL")
    os.environ["MOUNTAINEER_LOG_LEVEL"] = log_level
    try:
        yield current_log_level
    finally:
        if current_log_level is not None:
            os.environ["MOUNTAINEER_LOG_LEVEL"] = current_log_level
        else:
            del os.environ["MOUNTAINEER_LOG_LEVEL"]


@pytest.mark.parametrize(
    "log_level,should_create_file",
    [
        ("DEBUG", True),
        ("INFO", False),
        ("WARNING", False),
        ("ERROR", False),
    ],
)
def test_debug_log_artifact(log_level: str, should_create_file: bool):
    # Set up test environment
    test_content = "test content"
    test_prefix = "test"
    test_ext = "txt"

    # Reset any global state every run
    reset_artifact_dir()

    with modify_log_level(log_level):
        path = debug_log_artifact(test_prefix, test_ext, test_content)

    # Check the results
    if should_create_file:
        assert path is not None
        tmp_path = path.parent
        files = list(tmp_path.glob(f"{test_prefix}-*.{test_ext}"))

        assert len(files) == 1
        with open(files[0], "r") as f:
            assert f.read() == test_content
    else:
        assert path is None
