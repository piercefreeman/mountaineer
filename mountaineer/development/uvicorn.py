import asyncio
import logging
from threading import Thread
from time import sleep
from typing import Optional

from fastapi import FastAPI
from rich.live import Live
from rich.spinner import Spinner
from rich.style import Style
from rich.text import Text
from uvicorn import Config
from uvicorn.server import Server

from mountaineer.console import CONSOLE


class ServerStatus:
    def __init__(self, name: str, emoticon: str):
        self.status = "Starting server..."
        self.final_status: str | None = None
        self.url: str | None = None
        self.name = name
        self.emoticon = emoticon
        self._spinner = Spinner("dots", style="status.spinner", speed=1.0)

    def update(self, message: str, url: str | None = None, final: bool = False) -> None:
        self.status = message
        self.url = url
        if final:
            self.final_status = message

    def __rich__(self) -> Text | Spinner:
        if self.final_status:
            if self.url:
                text = Text()
                text.append(f"{self.emoticon} {self.name} ready at ", style="bold")
                text.append(self.url, style=Style(color="blue", underline=True))
                return text
            return Text(self.final_status)

        self._spinner.update(text=self.status)
        return self._spinner


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

    # Create our status tracker
    status = ServerStatus(name=name, emoticon=emoticon)

    # Increase refresh rate for smoother animation
    live = Live(status, console=CONSOLE, refresh_per_second=30)
    live.start()

    def log_adapter(logger_name: str):
        def _log(msg: str, *args, **kwargs):
            if "Started server process" in msg:
                process_id = args[0] if args else "Unknown"
                status.update(f"Starting server process [cyan]{process_id}[/cyan]...")
            elif "Waiting for application startup" in msg:
                status.update("Initializing application...")
            elif "Application startup complete" in msg:
                status.update("Application initialized...")
            elif "Uvicorn running on" in msg:
                scheme, host, port = (
                    args[:3] if len(args) >= 3 else ("http", "unknown", "unknown")
                )
                url = f"{scheme}://{host}:{port}"
                status.update("Server ready", url=url, final=True)
                live.stop()

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
