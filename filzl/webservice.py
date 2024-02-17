import asyncio
from threading import Thread

from fastapi import FastAPI
from uvicorn import Config
from uvicorn.server import Server


class UvicornThread(Thread):
    def __init__(self, *, app: FastAPI, port: int, log_level: str = "info"):
        super().__init__(daemon=True)
        self.app = app
        self.port = port
        self.log_level = log_level
        self.server: Server | None = None

    def run(self):
        loop = asyncio.new_event_loop()
        config = Config(
            app=self.app,
            port=self.port,
            reload=False,
            access_log=False,
            loop="asyncio",
            log_level=self.log_level,
        )
        self.server = Server(config)
        loop.run_until_complete(self.server.serve())

    def stop(self):
        if self.server is not None:
            self.server.should_exit = True
