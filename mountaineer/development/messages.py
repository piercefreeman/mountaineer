import asyncio
import os
import traceback
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
        LOGGER.debug("[AsyncMessageBroker] Initializing message broker")
        self.message_queue: Queue = Queue()
        self.response_queue: Queue = Queue()
        self._pending_futures: Dict[str, Future[Any]] = {}
        self._response_task: Optional[asyncio.Task] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._should_stop = False

    def __getstate__(self):
        """
        Custom pickling behavior to only serialize the queues.
        Other attributes will be reinitialized in the new process.
        """
        return {
            "message_queue": self.message_queue,
            "response_queue": self.response_queue,
        }

    def __setstate__(self, state):
        """
        Restore the broker state from pickle, reinitializing non-picklable components
        """
        self.message_queue = state["message_queue"]
        self.response_queue = state["response_queue"]
        self._pending_futures = {}
        self._response_task = None
        self._executor = None
        self._should_stop = False

    def start(self):
        """Start the response consumer task"""
        LOGGER.debug("[AsyncMessageBroker] Starting message broker")
        if self._response_task is None:
            self._executor = ThreadPoolExecutor(max_workers=1)
            self._should_stop = False
            self._response_task = asyncio.create_task(self._consume_responses())
            LOGGER.debug("[AsyncMessageBroker] Response consumer task created")

    async def stop(self):
        """Stop the response consumer task"""
        LOGGER.debug("[AsyncMessageBroker] Stopping message broker")
        self._should_stop = True

        if self._response_task is not None:
            LOGGER.debug("[AsyncMessageBroker] Cancelling response task")
            self._response_task.cancel()
            try:
                await self._response_task
            except asyncio.CancelledError:
                LOGGER.debug(
                    "[AsyncMessageBroker] Response task cancelled successfully"
                )
            except Exception as e:
                LOGGER.error(f"Error during task cancellation: {e}")
                LOGGER.debug(
                    f"[AsyncMessageBroker] Error during task cancellation: {e}"
                )

            self._response_task = None

        # Clean up executor
        if self._executor:
            LOGGER.debug("[AsyncMessageBroker] Shutting down executor")
            self._executor.shutdown(wait=False)
            self._executor = None

        # Clean up any remaining futures
        pending_count = len(self._pending_futures)
        LOGGER.debug(
            f"[AsyncMessageBroker] Cleaning up {pending_count} pending futures"
        )
        for message_id, future in self._pending_futures.items():
            if not future.done():
                LOGGER.debug(
                    f"[AsyncMessageBroker] Cancelling future for message {message_id}"
                )
                future.cancel()

        self._pending_futures.clear()

        # Drain queues
        try:
            LOGGER.debug("[AsyncMessageBroker] Draining message queues")
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
            LOGGER.debug(f"[AsyncMessageBroker] Error draining queues: {e}")
            LOGGER.error(f"Error draining queues: {e}")

    async def _consume_responses(self):
        """Consume responses from the response queue and resolve corresponding futures"""
        LOGGER.debug("[AsyncMessageBroker] Starting response consumer loop")
        LOGGER.debug(f"[AsyncMessageBroker] Current process: {os.getpid()}")
        while not self._should_stop:
            try:
                if not self._executor:
                    LOGGER.debug(
                        "[AsyncMessageBroker] Executor not available, breaking consumer loop"
                    )
                    break

                try:
                    LOGGER.debug(
                        "[AsyncMessageBroker] About to get from response queue..."
                    )

                    (
                        response_id,
                        response,
                    ) = await asyncio.get_event_loop().run_in_executor(
                        self._executor,
                        self.response_queue.get,
                        True,
                        0.1,  # timeout of 0.1s
                    )
                    LOGGER.debug(
                        f"[AsyncMessageBroker] Successfully received response from queue for message {response_id}"
                    )
                    LOGGER.debug(f"[AsyncMessageBroker] Response content: {response}")

                    if response_id in self._pending_futures:
                        LOGGER.debug(
                            f"[AsyncMessageBroker] Found pending future for message {response_id}"
                        )
                        future = self._pending_futures.pop(response_id)
                        if not future.done():
                            LOGGER.debug(
                                f"[AsyncMessageBroker] Setting result for message {response_id}"
                            )
                            future.set_result(response)
                            LOGGER.debug(
                                f"[AsyncMessageBroker] Successfully set result for message {response_id}"
                            )
                        else:
                            LOGGER.debug(
                                f"[AsyncMessageBroker] Future already completed for message {response_id}"
                            )
                    else:
                        LOGGER.debug(
                            f"[AsyncMessageBroker] No pending future found for message {response_id}"
                        )
                        LOGGER.debug(
                            f"[AsyncMessageBroker] Current pending futures: {list(self._pending_futures.keys())}"
                        )

                except Empty:
                    # This is expected when the queue times out
                    LOGGER.debug(
                        "[AsyncMessageBroker] Queue get timed out, continuing..."
                    )
                    continue
                except Exception as e:
                    LOGGER.debug(
                        f"[AsyncMessageBroker] Unexpected error during queue get: {str(e)}"
                    )
                    continue

            except asyncio.CancelledError:
                LOGGER.debug("[AsyncMessageBroker] Response consumer cancelled")
                raise
            except Exception as e:
                if not self._should_stop:
                    LOGGER.debug(f"[AsyncMessageBroker] Error consuming response: {e}")
                    LOGGER.debug(f"[AsyncMessageBroker] Error type: {type(e)}")
                    LOGGER.debug(
                        f"[AsyncMessageBroker] Error traceback: {traceback.format_exc()}"
                    )
                    LOGGER.error(f"Error consuming response: {e}", exc_info=True)

    def send_message(
        self, message: IsolatedMessageBase[TResponse]
    ) -> BrokerMessageFuture[TResponse]:
        """
        Send a message and return a future that will be resolved with the response
        """
        message_id = str(uuid.uuid4())
        LOGGER.debug(
            f"[AsyncMessageBroker] Sending message {message_id} of type {type(message).__name__}"
        )
        LOGGER.debug(f"[AsyncMessageBroker] Current process: {os.getpid()}")

        future = BrokerMessageFuture()
        self._pending_futures[message_id] = future
        LOGGER.debug(f"[AsyncMessageBroker] Created future for message {message_id}")
        LOGGER.debug(
            f"[AsyncMessageBroker] Current pending futures: {list(self._pending_futures.keys())}"
        )

        # Send message with ID
        LOGGER.debug("[AsyncMessageBroker] About to put message in queue")
        self.message_queue.put((message_id, message))
        LOGGER.debug(f"[AsyncMessageBroker] Message {message_id} placed in queue")
        return future
