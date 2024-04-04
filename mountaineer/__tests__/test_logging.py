import json
import logging
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO

from mountaineer.logging import setup_logger


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
