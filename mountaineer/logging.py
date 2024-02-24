import logging
from contextlib import contextmanager
from json import dumps as json_dumps
from logging import Formatter, StreamHandler, getLogger
from time import time

from click import secho


class JsonFormatter(Formatter):
    def format(self, record):
        log_record = {
            "level": record.levelname,
            "name": record.name,
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
    # TODO - env driven logging configuration

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
    start = time()
    yield
    LOGGER.debug(f"{message} : Took {time() - start:.2f}s")


LOGGER = setup_logger(__name__)
