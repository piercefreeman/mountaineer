import logging
from contextlib import contextmanager
from json import dumps as json_dumps
from logging import Formatter, StreamHandler, getLogger
from os import environ
from time import monotonic_ns

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
    Constructor for the main logger used by Mountaineer. Provided
    convenient defaults for log level and formatting, alongside coloring
    of stdout/stderr messages and JSON fields for structured parsing.

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
    LOGGER.debug(f"{message} : Took {(monotonic_ns() - start)/1e9:.2f}s")


# Our global logger should only surface warnings and above by default
LOGGER = setup_logger(
    __name__,
    log_level=VERBOSITY_MAPPING[environ.get("MOUNTAINEER_LOG_LEVEL", "WARNING")],
)
