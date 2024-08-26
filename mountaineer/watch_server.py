import asyncio
from multiprocessing import Queue
from threading import Thread

from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect

from mountaineer.io import get_free_port
from mountaineer.logging import LOGGER
from mountaineer.webservice import UvicornThread


class WatcherWebservice:
    """
    A simple webserver to notify frontends about updated builds.

    The WatcherWebservice provides a multiprocessing safe queue that's
    accessible as `notification_queue`. Each time that a process
    wants to update the frontend, it can push a message into the queue.

    """

    def __init__(self, webservice_host: str, webservice_port: int | None = None):
        self.app = self.build_app()
        self.websockets: list[WebSocket] = []
        self.host = webservice_host
        self.port = webservice_port or get_free_port()
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
        LOGGER.info("Broadcasted build update to %d listeners", len(self.websockets))

    def monitor_builds(self):
        while True:
            next_obj = self.notification_queue.get()
            if next_obj is None:
                break

            # Run in another thread's context
            asyncio.run(self.broadcast_listeners())

    def start(self):
        if self.has_started:
            raise Exception("WatcherWebservice has already started")

        # UvicornThreads are daemon threads by default
        self.webservice_thread = UvicornThread(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )

        LOGGER.debug("Starting WatcherWebservice on port %d", self.port)
        self.webservice_thread.start()

        self.monitor_build_thread = Thread(target=self.monitor_builds, daemon=True)
        self.monitor_build_thread.start()

        self.has_started = True

    def stop(self, wait_for_completion: int = 1) -> bool:
        """
        Attempts to stop the separate WatcherWebservice threads. We will send a termination
        signal to the threads and wait the desired interval for full completion. If the threads
        haven't exited after the interval, we will return False. Clients can then decide whether
        to send a harder termination signal to terminate the threads on the OS level.

        """
        success: bool = True
        if self.webservice_thread is not None:
            self.webservice_thread.stop()
            self.webservice_thread.join(wait_for_completion)
        if self.monitor_build_thread is not None:
            self.notification_queue.put(None)
            self.monitor_build_thread.join(wait_for_completion)

        if (self.webservice_thread and self.webservice_thread.is_alive()) or (
            self.monitor_build_thread and self.monitor_build_thread.is_alive()
        ):
            success = False
            LOGGER.info(
                f"WatcherWebservice still has outstanding threads: {self.webservice_thread} {self.monitor_build_thread}"
            )
        else:
            LOGGER.info("WatcherWebservice has fully stopped")

        return success
