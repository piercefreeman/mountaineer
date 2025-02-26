import asyncio
import uuid
from asyncio import Future
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from multiprocessing import Queue
from pathlib import Path
from queue import Empty
from typing import Any, Generic, TypeVar

from mountaineer.logging import LOGGER

TResponse = TypeVar("TResponse")


@dataclass
class IsolatedMessageBase(Generic[TResponse]):
    """Base class for all messages passed between main process and isolated app context"""

    pass


@dataclass
class ErrorResponse:
    """Generic error response"""

    exception: str
    traceback: str


@dataclass
class SuccessResponse:
    """Generic success response"""

    pass


@dataclass
class BootupMessage(IsolatedMessageBase[SuccessResponse | ErrorResponse]):
    """Message to bootup the isolated app context"""

    pass


@dataclass
class ReloadResponseSuccess(SuccessResponse):
    """Message indicating successful module reload"""

    reloaded: list[str]
    needs_restart: bool


@dataclass
class ReloadResponseError(ErrorResponse):
    """Error response for module reload"""

    reloaded: list[str]
    needs_restart: bool


@dataclass
class ReloadModulesMessage(
    IsolatedMessageBase[ReloadResponseSuccess | ReloadResponseError]
):
    """Message to reload modules in the isolated app context"""

    module_names: list[str]


@dataclass
class BuildJsMessage(IsolatedMessageBase[SuccessResponse | ErrorResponse]):
    """Message to trigger JS compilation"""

    updated_js: list[Path] | None


@dataclass
class BuildUseServerMessage(IsolatedMessageBase[SuccessResponse | ErrorResponse]):
    """Message to build the useServer support files"""

    pass


@dataclass
class StartCaptureLogsMessage(IsolatedMessageBase[SuccessResponse | ErrorResponse]):
    """Message to start capturing logs"""

    pass


@dataclass
class CaptureLogsSuccessResponse(SuccessResponse):
    """Message to capture logs"""

    captured_logs: str
    captured_errors: str


@dataclass
class StopCaptureLogsMessage(
    IsolatedMessageBase[CaptureLogsSuccessResponse | ErrorResponse]
):
    """Message to stop capturing logs"""

    pass


@dataclass
class RestartServerMessage(IsolatedMessageBase[SuccessResponse | ErrorResponse]):
    """
    Message to restart the server

    1. Load the new app controller in-memory
    2. Launch a new server

    This will not reload module files. For that, use the `ReloadModulesMessage`.

    """

    pass


@dataclass
class ShutdownMessage(IsolatedMessageBase[SuccessResponse | ErrorResponse]):
    """Message to shutdown the isolated app context"""

    pass


AppMessageType = TypeVar("AppMessageType", bound=IsolatedMessageBase[Any])


class BrokerMessageFuture(Generic[TResponse], asyncio.Future[TResponse]):
    pass


class AsyncMessageBroker(Generic[AppMessageType]):
    """
    A thread and process-safe message broker that allows async communication between
    processes. This broker maintains a mapping between message IDs and their corresponding
    futures, allowing async code to await responses from other processes.

    The broker uses two multiprocessing queues to facilitate bidirectional communication:
    - message_queue: Sends messages from the main process to the isolated process
    - response_queue: Sends responses from the isolated process back to the main process

    This is a core component of Mountaineer's process isolation architecture, enabling
    hot-reloading and development tooling while maintaining process separation.

    ```python {{sticky: True}}
    import asyncio
    from mountaineer.development.messages import (
        AsyncMessageBroker,
        ReloadModulesMessage,
        RestartServerMessage
    )

    # Create a broker in the main process
    broker = AsyncMessageBroker()
    broker.start()

    try:
        # Send a message to reload modules and await the response
        reload_future = broker.send_message(
            ReloadModulesMessage(module_names=["app.controllers", "app.models"])
        )
        reload_response = await reload_future

    finally:
        # Always stop the broker when done
        await broker.stop()

    ```
    """

    def __init__(self):
        """
        Initialize a new AsyncMessageBroker with empty message and response queues.

        Creates the necessary multiprocessing queues and initializes the internal state
        for tracking pending message futures. The broker must be explicitly started
        with the start() method before it can process messages.
        """
        self.message_queue: Queue = Queue()
        self.response_queue: Queue = Queue()
        self._pending_futures: dict[str, Future[Any]] = {}
        self._response_task: asyncio.Task | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._should_stop = False

    def __getstate__(self):
        """
        Only serialize the queues when transferring from our main to isolated process.

        Other attributes will be reinitialized in the new process so we don't
        attempt to share non-thread safe objects between processes.

        :return: Dictionary containing only the serializable state (message and response queues)
        """
        return {
            "message_queue": self.message_queue,
            "response_queue": self.response_queue,
        }

    def __setstate__(self, state: dict[str, Any]):
        """
        Restore the broker state from pickle, reinitializing non-picklable components.

        This is called when the broker is unpickled in the isolated process. It restores
        the queues and reinitializes the other attributes to their default values.

        :param state: Dictionary containing the serialized state
        """
        self.message_queue = state["message_queue"]
        self.response_queue = state["response_queue"]
        self._pending_futures = {}
        self._response_task = None
        self._executor = None
        self._should_stop = False

    def start(self):
        """
        Start the response consumer task.

        Initializes a ThreadPoolExecutor for consuming responses and creates an asyncio
        task to process responses from the response queue. This method must be called
        before sending any messages through the broker.
        """
        if self._response_task is None:
            self._executor = ThreadPoolExecutor(max_workers=1)
            self._should_stop = False
            self._response_task = asyncio.create_task(self._consume_responses())

    async def stop(self):
        """
        Stop the response consumer task and clean up resources.

        Cancels the response consumer task, shuts down the executor, cancels any pending
        futures, and drains the message and response queues. This method should be called
        when the broker is no longer needed to ensure proper cleanup of resources.
        """
        self._should_stop = True

        if self._response_task is not None:
            self._response_task.cancel()
            try:
                await self._response_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                LOGGER.error(f"Error during task cancellation: {e}")

            self._response_task = None

        # Clean up executor
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None

        # Clean up any remaining futures
        for message_id, future in self._pending_futures.items():
            if not future.done():
                future.cancel()

        self._pending_futures.clear()

        # Drain queues
        try:
            while not self.message_queue.empty():
                try:
                    self.message_queue.get_nowait()
                except Empty:
                    break
            while not self.response_queue.empty():
                try:
                    self.response_queue.get_nowait()
                except Empty:
                    break
        except Exception as e:
            LOGGER.error(f"Error draining queues: {e}")

    async def _consume_responses(self):
        """
        Consume responses from the response queue and resolve corresponding futures.

        This internal method runs as a background task, continuously polling the response
        queue for new responses. When a response is received, it finds the corresponding
        future by its ID and resolves it with the response value.
        """
        while not self._should_stop:
            try:
                if not self._executor:
                    break

                try:
                    (
                        response_id,
                        response,
                    ) = await asyncio.get_event_loop().run_in_executor(
                        self._executor,
                        self.response_queue.get,
                        True,
                        0.1,  # timeout of 0.1s
                    )

                    if response_id in self._pending_futures:
                        future = self._pending_futures.pop(response_id)
                        if not future.done():
                            future.set_result(response)

                except Empty:
                    continue
                except Exception:
                    continue

            except asyncio.CancelledError:
                raise
            except Exception as e:
                if not self._should_stop:
                    LOGGER.error(f"Error consuming response: {e}", exc_info=True)

    def send_message(
        self, message: IsolatedMessageBase[TResponse]
    ) -> BrokerMessageFuture[TResponse]:
        """
        Send a message and return a future that will be resolved with the response.

        This method generates a unique ID for the message, creates a future for the
        response, adds the future to the pending futures dictionary, and puts the
        message in the message queue. The future will be resolved when a response
        with the corresponding ID is received in the response queue.

        :param message: The message to send, which must be a subclass of IsolatedMessageBase
        :return: A future that will be resolved with the response
        """
        message_id = str(uuid.uuid4())
        future = BrokerMessageFuture[TResponse]()
        self._pending_futures[message_id] = future
        self.message_queue.put((message_id, message))
        return future
