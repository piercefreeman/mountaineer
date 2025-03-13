import asyncio
from multiprocessing import Queue
from threading import Thread

from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect

from mountaineer.development.uvicorn import UvicornThread
from mountaineer.io import get_free_port
from mountaineer.logging import LOGGER


class WatcherWebservice:
    """
    A simple webserver to notify frontends about updated builds via WebSockets.

    The WatcherWebservice provides a multiprocessing safe queue that's
    accessible as `notification_queue`. Each time that a process
    wants to update the frontend, it can push a message into the queue.

    This service is a critical component in the hot-reloading architecture,
    enabling backend changes to trigger frontend refreshes without manual intervention.
    It runs as a lightweight FastAPI application in a separate thread.

    """

    def __init__(self, webservice_host: str, webservice_port: int | None = None):
        """
        Initialize a new WatcherWebservice for notifying frontends about build updates.

        :param webservice_host: The host address to bind the webservice to (e.g. '127.0.0.1')
        :param webservice_port: Optional port number to use. If not provided, a free port will be allocated.
        """
        self.app = self.build_app()
        self.websockets: list[WebSocket] = []
        self.host = webservice_host
        self.port = webservice_port or get_free_port()
        self.notification_queue: Queue[bool | None] = Queue()

        self.webservice_thread: UvicornThread | None = None
        self.monitor_build_thread: Thread | None = None

        self.has_started = False

    def build_app(self):
        """
        Construct the FastAPI application with necessary routes and WebSocket endpoints.

        Creates a simple API with:
        - A root endpoint returning basic service information
        - A WebSocket endpoint at "/build-events" for real-time build notifications

        :return: Configured FastAPI application instance
        """
        app = FastAPI()

        @app.get("/")
        def home():
            return {"message": "This is the mountaineer hot-reload server."}

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
        """
        Send a notification to all connected WebSocket clients.

        This method is called when a new build is available, signaling
        all connected frontends to refresh.
        """
        for ws in self.websockets:
            await ws.send_text("Build updated")
        LOGGER.info("Broadcasted build update to %d listeners", len(self.websockets))

    def monitor_builds(self):
        """
        Monitor the notification queue and broadcast updates to connected clients.

        This method runs in a separate thread, blocking on the notification queue
        and calling broadcast_listeners when a notification is received. The thread
        terminates when None is pushed to the queue.
        """
        while True:
            next_obj = self.notification_queue.get()
            if next_obj is None:
                break

            # Run in another thread's context
            asyncio.run(self.broadcast_listeners())

    async def start(self):
        """
        Start the WatcherWebservice by launching the necessary threads.

        Initializes and starts:
        - A UvicornThread to serve the FastAPI application
        - A monitor thread to watch for build notifications

        :raises Exception: If the service has already been started
        """
        if self.has_started:
            raise Exception("WatcherWebservice has already started")

        # UvicornThreads are daemon threads by default
        self.webservice_thread = UvicornThread(
            name="Hot reload server",
            emoticon="🦉",
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            use_logs=False,
        )

        LOGGER.debug("Starting WatcherWebservice on port %d", self.port)
        await self.webservice_thread.astart()

        LOGGER.debug("Starting monitor build thread")
        self.monitor_build_thread = Thread(target=self.monitor_builds, daemon=True)
        self.monitor_build_thread.start()

        LOGGER.debug("Finished WatcherWebservice constructor")
        self.has_started = True

    async def stop(self, wait_for_completion: int = 1) -> bool:
        """
        Attempts to stop the separate WatcherWebservice threads.

        Sends termination signals to the Uvicorn server and monitor threads,
        then waits for them to complete within the specified timeout period.

        :param wait_for_completion: Seconds to wait for threads to terminate (default: 1)
        :return: True if all threads terminated successfully, False otherwise
        """
        success: bool = True
        if self.webservice_thread is not None:
            await self.webservice_thread.astop()
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
