import asyncio
import logging
from threading import Thread
from time import sleep
from typing import Optional

from fastapi import FastAPI
from uvicorn import Config
from uvicorn.server import Server

from mountaineer.logging import LOGGER


def configure_uvicorn_logging(name: str, emoticon: str, log_level: str) -> None:
    """
    Replace Uvicorn's default logging with an updating status display.
    """
    # Remove all existing handlers
    for logger_name in ["uvicorn", "uvicorn.error"]:
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = False
        logger.setLevel(log_level.upper())

    def log_adapter(logger_name: str):
        def _log(msg: str, *args, **kwargs):
            if logger_name == "uvicorn.error":
                LOGGER.error(msg, *args, **kwargs)
                return

        return _log

    # Replace the info methods directly
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    uvicorn_logger.info = log_adapter("uvicorn")  # type: ignore
    uvicorn_error_logger.info = log_adapter("uvicorn.error")  # type: ignore


class UvicornThread(Thread):
    def __init__(
        self,
        *,
        name: str,
        emoticon: str,
        app: FastAPI,
        host: str,
        port: int,
        log_level: str = "info",
        use_logs: bool = True,
    ):
        super().__init__(daemon=True)
        self.app = app
        self.port = port
        self.host = host
        self.log_level = log_level
        self.name = name
        self.emoticon = emoticon
        self.server: Optional[Server] = None
        self.use_logs = use_logs

    def run(self) -> None:
        # Configure logging before creating the server
        if self.use_logs:
            configure_uvicorn_logging(self.name, self.emoticon, self.log_level)

        loop = asyncio.new_event_loop()
        config = Config(
            app=self.app,
            host=self.host,
            port=self.port,
            reload=False,
            access_log=False,
            loop="asyncio",
            log_level=self.log_level,
        )

        server = Server(config)
        self.server = server

        loop.run_until_complete(server.serve())

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True

        # Wait until the server is stopped
        total_wait = 10
        remaining_wait = total_wait
        wait_interval = 0.1

        while self.is_alive():
            remaining_wait -= 1
            if remaining_wait <= 0:
                raise TimeoutError(
                    f"Server did not stop in {total_wait * wait_interval}s"
                )
            sleep(wait_interval)
