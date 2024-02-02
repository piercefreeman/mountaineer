import asyncio
from multiprocessing import Queue
from threading import Thread

from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect

from filzl.logging import LOGGER
from filzl.webservice import UvicornThread


class WatcherWebservice:
    """
    A simple webserver to notify frontends about updated builds.

    The WatcherWebservice provides a multiprocessing safe queue that's
    accessible as `notification_queue`. Each time that a process
    wants to update the frontend, it can push a message into the queue.

    """

    def __init__(self, webservice_port: int = 5015):
        self.app = self.build_app()
        self.websockets: list[WebSocket] = []
        self.webservice_port = webservice_port
        self.notification_queue: Queue[bool | None] = Queue()

        self.webservice_thread: UvicornThread | None = None
        self.monitor_build_thread: Thread | None = None

        self.has_started = False

    def build_app(self):
        app = FastAPI()

        @app.get("/")
        def home():
            return {"message": "Hello World"}

        @app.websocket("/build-events")
        async def build_updated(websocket: WebSocket):
            await websocket.accept()
            self.websockets.append(websocket)

            while True:
                # Keep the connection open until the client side disconnects
                try:
                    data = await websocket.receive_text()
                except WebSocketDisconnect:
                    # Expected exception, don't log an error
                    self.websockets.remove(websocket)
                    break
                await websocket.send_text(f"echo: {data}")

        return app

    async def broadcast_listeners(self):
        for ws in self.websockets:
            await ws.send_text("Build updated")

    def monitor_builds(self):
        while True:
            next_obj = self.notification_queue.get()
            if next_obj is None:
                break
            asyncio.run(self.broadcast_listeners())

    def start(self):
        if self.has_started:
            raise Exception("WatcherWebservice has already started")

        self.webservice_thread = UvicornThread(
            "filzl.watch_server:WATCHER_WEBSERVICE.app", self.webservice_port
        )
        self.webservice_thread.start()

        self.monitor_build_thread = Thread(target=self.monitor_builds)
        self.monitor_build_thread.start()

        self.has_started = True

    def stop(self):
        if self.webservice_thread is not None:
            self.webservice_thread.stop()
            self.webservice_thread.join()
        if self.monitor_build_thread is not None:
            self.notification_queue.put(None)
            self.monitor_build_thread.join()
        LOGGER.info("WatcherWebservice has stopped")


# One global variable to use for the uvicorn entrypoint
WATCHER_WEBSERVICE = WatcherWebservice()
