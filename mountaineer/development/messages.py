import asyncio
import uuid
from asyncio import Future
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from multiprocessing import Queue
from queue import Empty
from typing import Any, Dict, Generic, List, Optional, TypeVar

from mountaineer.logging import LOGGER

TResponse = TypeVar("TResponse")


@dataclass
class IsolatedMessageBase(Generic[TResponse]):
    """Base class for all messages passed between main process and isolated app context"""

    pass


@dataclass
class ReloadResponse(IsolatedMessageBase[None]):
    success: bool
    reloaded: list[str]
    needs_restart: bool
    exception: Optional[str] = None
    traceback: Optional[str] = None


@dataclass
class ReloadModulesMessage(IsolatedMessageBase[ReloadResponse]):
    """Message to reload modules in the isolated app context"""

    module_names: List[str]


@dataclass
class BuildJsMessage(IsolatedMessageBase[None]):
    """Message to trigger JS compilation"""

    pass


@dataclass
class ShutdownMessage(IsolatedMessageBase[None]):
    """Message to shutdown the isolated app context"""

    pass


AppMessageType = TypeVar("AppMessageType", bound=IsolatedMessageBase[Any])


class BrokerMessageFuture(Generic[TResponse], asyncio.Future):
    pass


class AsyncMessageBroker(Generic[AppMessageType]):
    """
    A thread and process-safe message broker that allows async communication between
    processes. This broker maintains a mapping between message IDs and their corresponding
    futures, allowing async code to await responses from other processes.
    """

    def __init__(self):
        self.message_queue: Queue = Queue()
        self.response_queue: Queue = Queue()
        self._pending_futures: Dict[str, Future[Any]] = {}
        self._response_task: Optional[asyncio.Task] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._should_stop = False

    def start(self):
        """Start the response consumer task"""
        if self._response_task is None:
            self._executor = ThreadPoolExecutor(max_workers=1)
            self._should_stop = False
            self._response_task = asyncio.create_task(self._consume_responses())

    async def stop(self):
        """Stop the response consumer task"""
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
        for future in self._pending_futures.values():
            if not future.done():
                future.cancel()

        self._pending_futures.clear()

        # Drain queues
        try:
            while not self.message_queue.empty():
                try:
                    self.message_queue.get_nowait()
                except:
                    break
            while not self.response_queue.empty():
                try:
                    self.response_queue.get_nowait()
                except:
                    break
        except Exception as e:
            LOGGER.error(f"Error draining queues: {e}")

    async def _consume_responses(self):
        """Consume responses from the response queue and resolve corresponding futures"""
        while not self._should_stop:
            try:
                # Use our dedicated executor
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
                    # This is expected when the queue times out
                    continue

            except asyncio.CancelledError:
                raise
            except Exception as e:
                if (
                    not self._should_stop
                ):  # Only log if we're not intentionally stopping
                    LOGGER.error(f"Error consuming response: {e}", exc_info=True)

    def send_message(
        self, message: IsolatedMessageBase[TResponse]
    ) -> BrokerMessageFuture[TResponse]:
        """
        Send a message and return a future that will be resolved with the response
        """
        message_id = str(uuid.uuid4())
        future = BrokerMessageFuture()
        self._pending_futures[message_id] = future

        # Send message with ID
        self.message_queue.put((message_id, message))
        return future
