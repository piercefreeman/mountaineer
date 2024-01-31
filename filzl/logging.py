from json import dumps as json_dumps
from logging import DEBUG, Formatter, StreamHandler, getLogger


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


def setup_logger(name, log_level=DEBUG):
    # TODO - env driven logging configuration

    logger = getLogger(name)
    logger.setLevel(log_level)

    # Create a handler that writes log records to the standard error
    handler = StreamHandler()
    handler.setLevel(log_level)

    formatter = JsonFormatter()
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    return logger


LOGGER = setup_logger(__name__)
