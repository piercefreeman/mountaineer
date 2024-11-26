import asyncio
import logging
from logging import getLogger
from threading import Thread
from time import sleep
from typing import Optional
from fastapi import FastAPI
from rich.logging import RichHandler
from uvicorn import Config
from uvicorn.server import Server
from mountaineer.console import CONSOLE

def configure_uvicorn_logging(log_level: str) -> None:
    """Replace Uvicorn's default logging completely."""
    # Remove all existing handlers
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.handlers = []
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    uvicorn_error_logger.handlers = []

    # Disable propagation to avoid double logging
    uvicorn_logger.propagate = False
    uvicorn_error_logger.propagate = False

    # Set levels
    uvicorn_logger.setLevel(log_level.upper())
    uvicorn_error_logger.setLevel(log_level.upper())

    # Create our custom logger
    def log_adapter(logger_name: str):
        def _log(msg: str, *args, **kwargs):
            if "Started server process" in msg:
                process_id = args[0] if args else "Unknown"
                CONSOLE.print(f"⚡️ Server process [cyan]{process_id}[/cyan]")
            elif "Waiting for application startup" in msg:
                CONSOLE.print("🔄 Initializing application...")
            elif "Application startup complete" in msg:
                CONSOLE.print("✨ Application ready")
            elif "Uvicorn running on" in msg:
                scheme, host, port = args[:3] if len(args) >= 3 else ("http", "unknown", "unknown")
                CONSOLE.print(f"🌎 Listening on [link]{scheme}://{host}:{port}[/link]")
        return _log

    # Replace the info methods directly
    uvicorn_logger.info = log_adapter("uvicorn")
    uvicorn_error_logger.info = log_adapter("uvicorn.error")

class UvicornThread(Thread):
    def __init__(
        self,
        *,
        app: FastAPI,
        host: str,
        port: int,
        log_level: str = "info"
    ):
        super().__init__(daemon=True)
        self.app = app
        self.port = port
        self.host = host
        self.log_level = log_level
        self.server: Optional[Server] = None

    def run(self) -> None:
        # Configure logging before creating the server
        configure_uvicorn_logging(self.log_level)

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
        self.server = Server(config)
        loop.run_until_complete(self.server.serve())

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
