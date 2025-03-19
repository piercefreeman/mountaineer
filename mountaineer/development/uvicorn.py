import asyncio
import socket
from threading import Thread
from time import time
from typing import Optional

from fastapi import FastAPI
from uvicorn import Config
from uvicorn.server import Server


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

    async def astart(self, timeout: int = 5) -> None:
        super().start()

        # Wait until the server has self-flagged server.started and it's bound to the
        # desired port. If we we timeout waiting for either signal, then raise an error.
        did_start = False
        start = time()
        while time() - start < timeout:
            is_mounted = (
                self.server and self.server.started and not self._is_port_free()
            )
            if is_mounted:
                did_start = True
                break

            await asyncio.sleep(0.1)

        if not did_start:
            raise TimeoutError(
                f"Server did not start in {timeout}s (checked {self.host}:{self.port})"
            )

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
