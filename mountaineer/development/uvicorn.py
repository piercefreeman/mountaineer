import asyncio
import logging
import socket
from threading import Thread
from time import time
from typing import Optional

from fastapi import FastAPI
from uvicorn import Config
from uvicorn.server import Server

from mountaineer.logging import LOGGER

KNOWN_OKAY_LOGS = [
    "Started server process",
    "Waiting for application startup",
    "Application startup complete",
    "Uvicorn running on",
    "Waiting for application shutdown",
    "Application shutdown complete",
    "Finished server process",
    "Shutting down",
]


def configure_uvicorn_logging(name: str, emoticon: str, log_level: str) -> None:
    """
    Uvicorn's default logging is too verbose for our development restart logic, so we
    replace it with a more concise logging system that only logs certain messages.

    KNOWN_OKAY_LOGS are logs that we expect to see and are not indicative of a problem.
    Otherwise we pass through error logs so users are still alerted of issues.

    """
    # Remove all existing handlers
    for logger_name in ["uvicorn", "uvicorn.error"]:
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = False
        logger.setLevel(log_level.upper())

    def log_adapter(logger_name: str):
        def _log(msg: str, *args, **kwargs):
            print("LOGGING", msg, args, kwargs, flush=True)
            is_okay = any(token in msg for token in KNOWN_OKAY_LOGS)
            if logger_name == "uvicorn.error" and not is_okay:
                LOGGER.error(msg, *args, **kwargs)
            else:
                LOGGER.debug(msg, *args, **kwargs)

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

        self.shutdown = False

    def run(self) -> None:
        # uvicorn.run(self.app, host=self.host, port=self.port)
        # return

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
            # log_level=self.log_level,
            log_level="debug",
        )

        server = Server(config)
        self.server = server

        print("RUNNING SERVER", flush=True)
        loop.run_until_complete(server.serve())

    async def astart(self, timeout: int = 5) -> None:
        super().start()
        return

        # Wait until the server has self-flagged server.started and it's bound to the
        # desired port. If we we timeout waiting for either signal, then raise an error.
        did_start = False
        start = time()
        while time() - start < timeout:
            is_mounted = (
                self.server and self.server.started and not self._is_port_free()
            )
            print("is_mounted", is_mounted, flush=True)
            if is_mounted:
                did_start = True
                break

            await asyncio.sleep(0.1)

        if not did_start:
            raise TimeoutError(f"Server did not start in {timeout}s")

    async def astop(self, timeout: int = 1) -> None:
        """
        Attempts to stop the server gracefully. If the server does not stop
        within the given timeout, then we forcefully kill the server.

        """
        if self.server is not None:
            self.server.should_exit = True

        # Check if the port is still bound
        did_stop = False
        start = time()
        while time() - start < timeout:
            if self._is_port_free():
                did_stop = True
                break

            await asyncio.sleep(0.1)

        # If we get here, the port is still bound after all our checks
        if not did_stop:
            raise TimeoutError(f"Server did not stop after {timeout}s")

    def start(self) -> None:
        raise NotImplementedError("Use astart() instead")

    def stop(self) -> None:
        raise NotImplementedError("Use astop() instead")

    def _is_port_free(self) -> bool:
        """
        Check if the port is free by attempting to bind to it.
        Returns True if the port is free, False if it's still in use.
        """
        try:
            # Create a socket and try to bind to the port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)  # Set a short timeout
                s.bind((self.host, self.port))
                # If we get here, binding succeeded, port is free
                return True
        except (socket.error, OSError):
            # Port is still in use
            return False
