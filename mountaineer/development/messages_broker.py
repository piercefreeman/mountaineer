import asyncio
import json
import pickle
import secrets
import socket
from asyncio import Future
from base64 import b64decode, b64encode
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Thread
from typing import Annotated, Any, Generic, Literal, TypeVar, cast
from uuid import uuid4

from pydantic import BaseModel, Field, TypeAdapter

from mountaineer.development.messages import ErrorResponse
from mountaineer.logging import LOGGER

TResponse = TypeVar("TResponse")
AppMessageTypes = TypeVar("AppMessageTypes")


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


class BaseCommand(BaseModel):
    """Base class for all broker commands with authentication"""

    auth_key: str


class SendJobCommand(BaseCommand):
    """Command to send a new job to the broker"""

    item_type: Literal["send_job"] = "send_job"
    job_id: str
    job_data: Any


class SendResponseCommand(BaseCommand):
    """Command to send a response for a job"""

    item_type: Literal["send_response"] = "send_response"
    job_id: str
    response_data: Any


class GetResponseCommand(BaseCommand):
    """Command to get a response for a job"""

    item_type: Literal["get_response"] = "get_response"
    job_id: str


class GetJobCommand(BaseCommand):
    """Command to get the next available job"""

    item_type: Literal["get_job"] = "get_job"


class DrainQueueCommand(BaseCommand):
    """Command to drain all jobs from the queue"""

    item_type: Literal["drain_queue"] = "drain_queue"


class BaseResponse(BaseModel):
    """Base class for all broker responses"""


class OKResponse(BaseResponse):
    """Response indicating successful command execution"""

    item_type: Literal["ok"] = "ok"
    response_data: Any | None = None


class UnauthorizedResponse(BaseResponse):
    """Response indicating authentication failure"""

    item_type: Literal["error"] = "error"
    message: str = "Invalid authentication key"


class BrokerAuthenticationError(Exception):
    """Raised when the broker authentication fails."""

    pass


class BrokerExecutionError(Exception):
    """Raised when the broker execution fails."""

    def __init__(self, error: str, traceback: str):
        super().__init__(error)
        self.error = error
        self.traceback = traceback


CommandTypes = (
    SendJobCommand
    | SendResponseCommand
    | GetResponseCommand
    | GetJobCommand
    | DrainQueueCommand
)
ResponseTypes = OKResponse | UnauthorizedResponse

# Create type adapters for polymorphic validation
command_type_adapter = TypeAdapter(  # type: ignore
    Annotated[CommandTypes, Field(discriminator="item_type")]
)

response_type_adapter = TypeAdapter(  # type: ignore
    Annotated[ResponseTypes, Field(discriminator="item_type")]
)


class AsyncMessageBroker(Thread, Generic[AppMessageTypes]):
    """
    A simple process-independent message broker server. This works around limitations
    with `multiprocessing.Queue` that require all processes to be related to the central
    running parent process (for sharing of file descriptors). Since exec processes are
    launched separately by firehot this inheritance isn't possible.

    On Linux we could work around this by using `mkfifo` but since there's no Windows
    equivalent for it, we use a simple port-based server to keep things multi-platform.

    """

    def __init__(
        self, *, host: str = "127.0.0.1", port: int = 0, auth_key: str | None = None
    ):
        """
        :param port: If set to 0, the server will choose a free port.
        :param auth_key: If provided, the server will check that the client's auth key matches.
        """
        super().__init__()
        self.host = host
        self.port = port
        self.auth_key = auth_key or secrets.token_hex(16)
        self.jobs: dict[str, Any] = {}  # job_id -> job_data
        self.job_queue: list[str] = []  # FIFO queue of job_ids
        self.responses: dict[str, Any] = {}  # job_id -> response_data
        self.pending_futures: dict[
            str, list[Future]
        ] = {}  # job_id -> list of asyncio.Future waiting for a response
        self.pending_job_futures: list[
            Future
        ] = []  # list of futures waiting for next job

        self.loop: asyncio.AbstractEventLoop | None = None
        self.server: asyncio.AbstractServer | None = None

        # Thread control.
        self.is_running = False
        self.should_stop = False

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
        LOGGER.info(f"JobBrokerServer started on {self.host}:{self.port}")

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
                self.loop.run_until_complete(asyncio.wait(pending, timeout=5.0))

            self.loop.close()
            self.is_running = False

    async def stop_server(self):
        """Stop the broker server and clean up resources."""
        if not self.is_running:
            return
        if not self.loop:
            raise RuntimeError("Broker server async loop not running")

        self.should_stop = True

        # Cancel all pending futures
        for futures in self.pending_futures.values():
            for future in futures:
                if not future.done():
                    future.cancel()
        self.pending_futures.clear()

        # Cancel pending job futures
        for future in self.pending_job_futures:
            if not future.done():
                future.cancel()
        self.pending_job_futures.clear()

        if self.server:
            try:
                self.server.close()
            except TypeError:
                # Expected error during failed _wakeup in base_events:close()
                pass
            # Schedule wait_closed on the broker's loop
            fut = asyncio.run_coroutine_threadsafe(self.server.wait_closed(), self.loop)
            await asyncio.wrap_future(fut)

        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

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

                response: BaseResponse | None = None

                if not self.loop:
                    raise RuntimeError("Broker server async loop not running")

                try:
                    # Deserialize incoming JSON message using the type adapter
                    message_dict = json.loads(data.decode())
                    try:
                        cmd_obj = command_type_adapter.validate_python(message_dict)
                    except Exception as e:
                        raise ValueError(f"Invalid command format: {e}")

                    # Validate auth key
                    if cmd_obj.auth_key != self.auth_key:
                        response = UnauthorizedResponse()
                        writer.write(
                            (json.dumps(response.model_dump()) + "\n").encode()
                        )
                        await writer.drain()
                        continue

                    # Process command based on its type
                    if isinstance(cmd_obj, SendJobCommand):
                        self.jobs[cmd_obj.job_id] = cmd_obj.job_data
                        self.job_queue.append(cmd_obj.job_id)
                        # If any futures are waiting for jobs, notify one of them
                        if self.pending_job_futures:
                            fut = self.pending_job_futures.pop(0)
                            if not fut.done():
                                fut.set_result(
                                    {
                                        "job_id": cmd_obj.job_id,
                                        "job_data": cmd_obj.job_data,
                                    }
                                )
                        response = OKResponse()
                    elif isinstance(cmd_obj, SendResponseCommand):
                        self.responses[cmd_obj.job_id] = cmd_obj.response_data
                        # If any futures are waiting, notify them
                        if cmd_obj.job_id in self.pending_futures:
                            for fut in self.pending_futures[cmd_obj.job_id]:
                                if not fut.done():
                                    fut.set_result(cmd_obj.response_data)
                            del self.pending_futures[cmd_obj.job_id]
                        response = OKResponse()
                    elif isinstance(cmd_obj, GetResponseCommand):
                        if cmd_obj.job_id in self.responses:
                            response = OKResponse(
                                response_data=self.responses[cmd_obj.job_id]
                            )
                        else:
                            fut = self.loop.create_future()
                            self.pending_futures.setdefault(cmd_obj.job_id, []).append(
                                fut
                            )
                            response_data = await fut
                            response = OKResponse(response_data=response_data)
                    elif isinstance(cmd_obj, GetJobCommand):
                        if self.job_queue:
                            # Get next job from queue
                            job_id = self.job_queue.pop(0)
                            response = OKResponse(
                                response_data={
                                    "job_id": job_id,
                                    "job_data": self.jobs[job_id],
                                }
                            )
                        else:
                            # No jobs available, create a future to wait for one
                            fut = self.loop.create_future()
                            self.pending_job_futures.append(fut)
                            try:
                                job_info = await fut
                                response = OKResponse(response_data=job_info)
                            except asyncio.CancelledError:
                                response = UnauthorizedResponse(
                                    message="Operation cancelled"
                                )
                    elif isinstance(cmd_obj, DrainQueueCommand):
                        # Return all jobs in the queue at once
                        jobs = []
                        while self.job_queue:
                            job_id = self.job_queue.pop(0)
                            jobs.append(
                                {
                                    "job_id": job_id,
                                    "job_data": self.jobs[job_id],
                                }
                            )
                        response = OKResponse(response_data=jobs)
                    else:
                        response = UnauthorizedResponse(
                            message="Unhandled command type"
                        )
                except Exception as e:
                    response = UnauthorizedResponse(message=str(e))

                # Send back response as JSON
                writer.write((json.dumps(response.model_dump()) + "\n").encode())
                await writer.drain()
        except Exception as e:
            response = UnauthorizedResponse(message=str(e))
            writer.write((json.dumps(response.model_dump()) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()

    #
    # Direct client API methods
    # These are callable from other threads/processes to communicate with the central server.
    #

    async def send_job(self, job_id: str, job_data: AppMessageTypes) -> BaseResponse:
        """
        Send a job to the broker server and wait for acknowledgement.
        """
        cmd = SendJobCommand(
            job_id=job_id,
            job_data=b64encode(pickle.dumps(job_data)).decode(),
            auth_key=self.auth_key,
        )
        response = await self._send_message(self.host, self.port, cmd)
        if isinstance(response, UnauthorizedResponse):
            raise BrokerAuthenticationError(response.message)
        return response

    async def send_response(
        self, job_id: str, response_data: TResponse
    ) -> BaseResponse:
        """
        Send a response for a job to the broker server.
        """
        cmd = SendResponseCommand(
            job_id=job_id,
            response_data=b64encode(pickle.dumps(response_data)).decode(),
            auth_key=self.auth_key,
        )
        response = await self._send_message(self.host, self.port, cmd)
        if isinstance(response, UnauthorizedResponse):
            raise BrokerAuthenticationError(response.message)
        return response

    async def get_response(self, job_id: str) -> Any:
        """
        Get a response for a job from the broker server.
        If the response is not available, wait for it.
        """
        cmd = GetResponseCommand(job_id=job_id, auth_key=self.auth_key)
        response = await self._send_message(self.host, self.port, cmd)
        if isinstance(response, UnauthorizedResponse):
            raise BrokerAuthenticationError(response.message)
        if not isinstance(response, OKResponse):
            raise ValueError(f"Failed to get response: {response}")
        if response.response_data is None:
            raise ValueError("No response data")
        return pickle.loads(b64decode(response.response_data))

    async def get_job(self) -> tuple[str, AppMessageTypes]:
        """
        Get the next available job from the broker server.
        If no jobs are available, wait for one.

        Returns:
            A dictionary containing 'job_id' and 'job_data' keys
        """
        cmd = GetJobCommand(auth_key=self.auth_key)
        response = await self._send_message(self.host, self.port, cmd)
        if isinstance(response, UnauthorizedResponse):
            raise BrokerAuthenticationError(response.message)
        if not isinstance(response, OKResponse):
            raise ValueError(f"Failed to get job: {response}")
        if response.response_data is None:
            raise ValueError("No job data")
        return response.response_data["job_id"], pickle.loads(
            b64decode(response.response_data["job_data"])
        )

    async def send_and_get_response(self, job_data: AppMessageTypes) -> Any:
        """
        Send a job to the broker server and wait for a response. Will raise on a client
        error to break out of the current loop.

        """
        job_id = str(uuid4())
        await self.send_job(job_id, job_data)
        response = await self.get_response(job_id)
        if isinstance(response, ErrorResponse):
            raise BrokerExecutionError(response.exception, response.traceback)
        return response

    async def drain_queue(self) -> list[tuple[str, AppMessageTypes]]:
        """
        Process all pending messages in the queue until it's empty.
        Returns immediately with all currently queued messages.

        Returns:
            A list of tuples containing (job_id, job_data) for all jobs that were in the queue.
        """
        cmd = DrainQueueCommand(auth_key=self.auth_key)
        response = await self._send_message(self.host, self.port, cmd)
        if isinstance(response, UnauthorizedResponse):
            raise BrokerAuthenticationError(response.message)
        if not isinstance(response, OKResponse):
            raise ValueError(f"Failed to drain queue: {response}")
        if response.response_data is None:
            return []

        return [
            (job["job_id"], pickle.loads(b64decode(job["job_data"])))
            for job in response.response_data
        ]

    async def _send_message(
        self, host: str, port: int, message_obj: BaseCommand
    ) -> BaseResponse:
        """
        Helper function to send a command message and receive the response asynchronously.
        """
        reader, writer = await asyncio.open_connection(host, port)
        try:
            json_msg = json.dumps(message_obj.model_dump()) + "\n"
            LOGGER.debug(f"Sending message to broker: {json_msg}")
            writer.write(json_msg.encode())
            await writer.drain()

            response_line = await reader.readline()
            response_dict = json.loads(response_line.decode())
            LOGGER.debug(f"Received server response: {response_dict}")

            return cast(
                BaseResponse, response_type_adapter.validate_python(response_dict)
            )
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
            yield (
                server,
                BrokerServerConfig(
                    host=server.host, port=server.port, auth_key=server.auth_key
                ),
            )
        finally:
            await server.stop_server()
            server.join(timeout=5.0)  # Wait for thread to finish with timeout
            if server.is_alive():
                LOGGER.warning("Warning: Server thread did not shut down cleanly")

    @classmethod
    @asynccontextmanager
    async def new_client(cls, config: BrokerServerConfig):
        client = cls(host=config.host, port=config.port, auth_key=config.auth_key)
        yield client
