import asyncio
from threading import Thread

from uvicorn import Config
from uvicorn.server import Server


class UvicornThread(Thread):
    def __init__(self, entrypoint: str, port: int):
        super().__init__(daemon=True)
        self.entrypoint = entrypoint
        self.port = port

    def run(self, port: int = 5006):
        # Manually constructing the runloop is required, otherwise we'll see errors
        # during thread shutdown about "asynio.CancelledError"
        loop = asyncio.new_event_loop()
        config = Config(
            self.entrypoint,
            port=self.port,
            reload=False,
            access_log=False,
            # The typehint for loop is incorrect, this actually does accept a loop
            loop=loop,  # type: ignore
        )
        self.server = Server(config)
        loop.run_until_complete(self.server.serve())

    def stop(self):
        self.server.should_exit = True
        self.server.force_exit = True
