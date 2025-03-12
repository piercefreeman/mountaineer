import asyncio
import json
import secrets
import socket
from asyncio import Future
from contextlib import contextmanager, asynccontextmanager
from dataclasses import asdict, dataclass
from threading import Thread
from typing import Any, Generic, Optional, TypeVar

from mountaineer.development.messages import IsolatedMessageBase

TResponse = TypeVar("TResponse")
AppMessageType = TypeVar("AppMessageType", bound=IsolatedMessageBase[Any])
AppMessageTypes = TypeVar("AppMessageTypes", bound=tuple[AppMessageType, ...])


class BrokerMessageFuture(Generic[TResponse], asyncio.Future[TResponse]):
    pass


@dataclass
class BrokerServerConfig(Generic[AppMessageTypes]):
    """
    Config required to access a server that controls queues
    in a separate thread.
    """

    host: str
    port: int
    auth_key: str


@dataclass
class BaseCommand:
    command: str
    auth_key: str


@dataclass
class SendJobCommand(BaseCommand):
    job_id: str
    job_data: Any


@dataclass
class SendResponseCommand(BaseCommand):
    job_id: str
    response_data: Any


@dataclass
class GetResponseCommand(BaseCommand):
    job_id: str


@dataclass
class BaseResponse:
    status: str
    message: Optional[str] = None


@dataclass
class OKResponse(BaseResponse):
    response_data: Any = None


@dataclass
class UnauthorizedResponse(BaseResponse):
    pass


# Mapping from command name to its corresponding dataclass.
COMMAND_MAP = {
    "send_job": SendJobCommand,
    "send_response": SendResponseCommand,
    "get_response": GetResponseCommand,
}


class BrokerAuthenticationError(Exception):
    """Raised when the broker authentication fails."""
    pass


class AsyncMessageBroker(Thread):
    """
    A simple process-independent message broker server. This works around limitations
    with `multiprocessing.Queue` that require all processes to be related to the central
    running parent process (for sharing of file descriptors). Since exec processes are
    launched separately by firehot this inheritance isn't possible.

    On Linux we could work around this by using `mkfifo` but since there's no Windows
    equivalent for it, we use a simple port-based server to keep things multi-platform.

    """

    def __init__(self, *, host: str = "127.0.0.1", port: int = 0, auth_key: str | None = None):
        """
        :param port: If set to 0, the server will choose a free port.
        :param auth_key: If provided, the server will check that the client's auth key matches.
        """
        super().__init__()
        self.host = host
        self.port = port
        self.auth_key = auth_key or secrets.token_hex(16)
        self.jobs: dict[str, Any] = {}  # job_id -> job_data (if needed)
        self.responses: dict[str, Any] = {}  # job_id -> response_data
        self.pending_futures: dict[
            str, list[Future]
        ] = {}  # job_id -> list of asyncio.Future waiting for a response

        self.loop = None
        self.server = None

        # Thread control.
        self.is_running = False
        self.should_stop = False

    async def stop(self):
        if not self.is_running:
            return

        self.should_stop = True

        # Cancel all pending futures
        for futures in self.pending_futures.values():
            for future in futures:
                if not future.done():
                    future.cancel()
        self.pending_futures.clear()

        if self.server:
            self.server.close()
            # Schedule wait_closed on the broker's loop
            fut = asyncio.run_coroutine_threadsafe(self.server.wait_closed(), self.loop)
            await asyncio.wrap_future(fut)

        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

    def run(self):
        # Create and set the event loop for this thread.
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # Determine a free port if needed.
        if self.port == 0:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((self.host, 0))
                self.port = s.getsockname()[1]

        # Start the asyncio TCP server.
        coro = asyncio.start_server(self.handle_client, self.host, self.port)
        self.server = self.loop.run_until_complete(coro)
        print(f"JobBrokerServer started on {self.host}:{self.port}")

        self.is_running = True

        try:
            self.loop.run_forever()
        finally:
            # Clean up
            if self.server:
                self.server.close()
                self.loop.run_until_complete(self.server.wait_closed())
            
            # Cancel all pending tasks
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            
            # Wait for all tasks to complete with a timeout
            if pending:
                self.loop.run_until_complete(
                    asyncio.wait(pending, timeout=5.0)
                )
            
            self.loop.close()
            self.is_running = False

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """
        Handle incoming client connections using a JSON-over-TCP protocol.
        Each JSON message corresponds to one of our command dataclasses.
        """
        try:
            while not self.should_stop:
                try:
                    data = await reader.readline()
                    if not data:
                        break  # connection closed
                except (ConnectionError, asyncio.CancelledError):
                    break

                try:
                    # Deserialize incoming JSON message to a dict.
                    message_dict = json.loads(data.decode())
                    cmd_type = message_dict.get("command")
                    if cmd_type in COMMAND_MAP:
                        # Instantiate the appropriate dataclass.
                        cmd_obj = COMMAND_MAP[cmd_type](**message_dict)
                    else:
                        raise ValueError(f"Unknown command: {cmd_type}")

                    # Validate auth key
                    if cmd_obj.auth_key != self.auth_key:
                        response = UnauthorizedResponse(
                            status="error",
                            message="Invalid authentication key"
                        )
                        writer.write((json.dumps(asdict(response)) + "\n").encode())
                        await writer.drain()
                        continue

                    # Process command based on its type.
                    if isinstance(cmd_obj, SendJobCommand):
                        self.jobs[cmd_obj.job_id] = cmd_obj.job_data
                        response = OKResponse(status="ok")
                    elif isinstance(cmd_obj, SendResponseCommand):
                        self.responses[cmd_obj.job_id] = cmd_obj.response_data
                        # If any futures are waiting, notify them.
                        if cmd_obj.job_id in self.pending_futures:
                            for fut in self.pending_futures[cmd_obj.job_id]:
                                if not fut.done():
                                    fut.set_result(cmd_obj.response_data)
                            del self.pending_futures[cmd_obj.job_id]
                        response = OKResponse(status="ok")
                    elif isinstance(cmd_obj, GetResponseCommand):
                        if cmd_obj.job_id in self.responses:
                            response = OKResponse(
                                status="ok", response_data=self.responses[cmd_obj.job_id]
                            )
                        else:
                            fut = self.loop.create_future()
                            self.pending_futures.setdefault(cmd_obj.job_id, []).append(fut)
                            response_data = await fut
                            response = OKResponse(status="ok", response_data=response_data)
                    else:
                        response = BaseResponse(
                            status="error", message="Unhandled command type"
                        )
                except Exception as e:
                    response = BaseResponse(status="error", message=str(e))

                # Send back response as JSON.
                writer.write((json.dumps(asdict(response)) + "\n").encode())
                await writer.drain()
        except Exception as e:
            response = BaseResponse(status="error", message=str(e))
            writer.write((json.dumps(asdict(response)) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()

    #
    # Direct client API methods
    # These are callable from other threads/processes to communicate with the central server.
    #

    async def send_job(self, job_id: str, job_data: Any) -> OKResponse:
        """
        Send a job to the broker server and wait for acknowledgement.
        """
        cmd = SendJobCommand(command="send_job", job_id=job_id, job_data=job_data, auth_key=self.auth_key)
        response = await self._send_message(self.host, self.port, cmd)
        if response.get("status") == "error" and isinstance(response.get("message"), str) and "authentication" in response.get("message").lower():
            raise BrokerAuthenticationError(response.get("message"))
        return OKResponse(**response)

    async def send_response(self, job_id: str, response_data: Any) -> OKResponse:
        """
        Send a response for a job to the broker server.
        """
        cmd = SendResponseCommand(command="send_response", job_id=job_id, response_data=response_data, auth_key=self.auth_key)
        response = await self._send_message(self.host, self.port, cmd)
        if response.get("status") == "error" and isinstance(response.get("message"), str) and "authentication" in response.get("message").lower():
            raise BrokerAuthenticationError(response.get("message"))
        return OKResponse(**response)

    async def get_response(self, job_id: str) -> Any:
        """
        Get a response for a job from the broker server.
        If the response is not available, wait for it.
        """
        cmd = GetResponseCommand(command="get_response", job_id=job_id, auth_key=self.auth_key)
        response = await self._send_message(self.host, self.port, cmd)
        if response.get("status") == "error":
            if isinstance(response.get("message"), str) and "authentication" in response.get("message").lower():
                raise BrokerAuthenticationError(response.get("message"))
            raise ValueError(f"Failed to get response: {response.get('message', 'Unknown error')}")
        if "response_data" in response:
            return response["response_data"]
        raise ValueError("Response data not found in server response")

    async def _send_message(self, host: str, port: int, message_obj: BaseCommand) -> dict:
        """
        Helper function to send a dataclass message (converted to JSON) and receive the response asynchronously.
        """
        reader, writer = await asyncio.open_connection(host, port)
        try:
            json_msg = json.dumps(asdict(message_obj)) + "\n"
            writer.write(json_msg.encode())
            await writer.drain()

            response_line = await reader.readline()
            return json.loads(response_line.decode())
        finally:
            writer.close()
            await writer.wait_closed()

    @classmethod
    @asynccontextmanager
    async def start_server(cls):
        server = cls()
        server.start()

        # Wait for the server to start.
        while not server.is_running:
            await asyncio.sleep(0.1)

        try:
            yield server, BrokerServerConfig(host=server.host, port=server.port, auth_key=server.auth_key)
        finally:
            await server.stop()
            server.join(timeout=5.0)  # Wait for thread to finish with timeout
            if server.is_alive():
                print("Warning: Server thread did not shut down cleanly")

    @classmethod
    @asynccontextmanager
    async def new_client(cls, config: BrokerServerConfig):
        client = cls(host=config.host, port=config.port, auth_key=config.auth_key)
        yield client
