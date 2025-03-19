import logging
from contextlib import contextmanager
from json import dumps as json_dumps
from logging import Formatter, StreamHandler, getLogger
from os import environ
from pathlib import Path
from tempfile import mkdtemp
from time import monotonic_ns, time

from click import secho

VERBOSITY_MAPPING = {
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class JsonFormatter(Formatter):
    def format(self, record):
        log_record = {
            "level": record.levelname,
            "name": record.name,
            "timestamp": self.formatTime(record, self.datefmt),
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json_dumps(log_record)


class ColorHandler(StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            if record.levelno == logging.WARNING:
                secho(msg, fg="yellow")
            elif record.levelno >= logging.ERROR:
                secho(msg, fg="red")
            else:
                secho(msg)
        except Exception:
            self.handleError(record)


def setup_logger(name, log_level=logging.DEBUG):
    """
    Constructor for the main logger used by Mountaineer and optionally for client
    applications as well. Provided convenient defaults for log level and formatting,
    alongside coloring of stdout/stderr messages and JSON fields for structured parsing.

    Logs are formatted one per line:
    ```json
    {"level": "INFO", "name": "myapp.logging", "timestamp": "2025-02-25 20:40:35,896", "message": "Application started"}
    ```

    To grep over these logs and filter for level, do:

    ```bash
    # Filter for specific log level
    grep '"level": "ERROR"' logfile.txt

    # Filter logs by service name
    grep '"name": "myapp.logging"' logfile.txt

    # With jq for more advanced JSON parsing
    cat logfile.txt | jq 'select(.level=="ERROR" or .level=="WARNING")'

    # Filter by message content
    grep -E '"message": ".*database.*"' logfile.txt
    ```

    ```python {{sticky: True}}
    from mountaineer.logging import setup_logger
    import logging

    # Create a logger for your module
    logger = setup_logger(__name__, log_level=logging.INFO)

    # Use the logger
    logger.info("Application started")
    logger.warning("Configuration incomplete")
    logger.error("Failed to connect to database")
    ```

    :param name: The name of the logger, typically the module name
    :param log_level: The logging level. Defaults to logging.DEBUG to log everything.

    :return: A configured logger instance

    """
    logger = getLogger(name)
    logger.setLevel(log_level)

    # Create a handler that writes log records to the standard error
    handler = ColorHandler()
    handler.setLevel(log_level)

    formatter = JsonFormatter()
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    return logger


@contextmanager
def log_time_duration(message: str):
    """
    Context manager to time a code block at runtime.

    ```python
    with log_time_duration("Long computation"):
        # Simulate work
        sleep(10)
    ```

    """
    start = monotonic_ns()
    yield
    LOGGER.debug(f"{message} : Took {(monotonic_ns() - start) / 1e9:.2f}s")


def setup_internal_logger(name: str):
    """
    Our global logger should only surface warnings and above by default.

    To adjust Mountaineer logging, set the MOUNTAINEER_LOG_LEVEL environment
    variable in your local session. By default it is set to WARNING and above.

    """
    return setup_logger(
        name,
        log_level=VERBOSITY_MAPPING[environ.get("MOUNTAINEER_LOG_LEVEL", "WARNING")],
    )


def pluralize(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


RUNTIME_ARITFACT_TMP_DIR: Path | None = None


def debug_log_artifact(artifact_prefix: str, extension: str, content: str):
    global RUNTIME_ARITFACT_TMP_DIR

    # Only log during highest level of verbosity
    if (
        VERBOSITY_MAPPING[environ.get("MOUNTAINEER_LOG_LEVEL", "WARNING")]
        > logging.DEBUG
    ):
        return

    if RUNTIME_ARITFACT_TMP_DIR is None:
        RUNTIME_ARITFACT_TMP_DIR = Path(mkdtemp())
        LOGGER.warning(
            f"Created temporary directory for runtime artifacts: {RUNTIME_ARITFACT_TMP_DIR}"
        )

    path = RUNTIME_ARITFACT_TMP_DIR / f"{artifact_prefix}-{time()}.{extension}"
    path.write_text(content)

    return path


def reset_artifact_dir():
    global RUNTIME_ARITFACT_TMP_DIR
    RUNTIME_ARITFACT_TMP_DIR = None


LOGGER = setup_internal_logger(__name__)
