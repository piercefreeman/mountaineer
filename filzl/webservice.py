import asyncio
from threading import Thread

from uvicorn import Config
from uvicorn.server import Server
from multiprocessing import Process, Event


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

class UvicornProcess(Process):
    """
    We need a fully separate process for our runserver, so we're able to re-import
    all of the dependent files when there are changes.

    """
    def __init__(self, entrypoint: str, port: int):
        super().__init__()
        self.close_signal = Event()
        self.entrypoint = entrypoint
        self.port = port

    def run(self):
        thread = UvicornThread(self.entrypoint, self.port)
        thread.start()
        self.close_signal.wait()
        thread.stop()
        thread.join()

    def stop(self):
        self.close_signal.set()
