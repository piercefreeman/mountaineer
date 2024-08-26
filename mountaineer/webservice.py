import asyncio
from logging import getLogger
from threading import Thread
from time import sleep

from fastapi import FastAPI
from rich.logging import RichHandler
from uvicorn import Config
from uvicorn.server import Server

from mountaineer.console import CONSOLE


class UvicornThread(Thread):
    def __init__(self, *, app: FastAPI, host: str, port: int, log_level: str = "info"):
        super().__init__(daemon=True)
        self.app = app
        self.port = port
        self.host = host
        self.log_level = log_level
        self.server: Server | None = None

    def run(self):
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

        # We override the default logging of uvicorn to use rich for logging
        logger = getLogger("uvicorn")
        logger.handlers = []
        rich_handler = RichHandler(console=CONSOLE)
        logger.addHandler(rich_handler)

        loop.run_until_complete(self.server.serve())

    def stop(self):
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
                    f"Server did not stop in {total_wait*wait_interval}s"
                )
            sleep(wait_interval)
