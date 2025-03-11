import asyncio
from queue import Empty

import pytest
import pytest_asyncio

from mountaineer.development.messages import IsolatedMessageBase
from mountaineer.development.messages_broker import (
    AsyncMessageBroker,
    BrokerMessageFuture,
)


class DummyMessage(IsolatedMessageBase):
    def __init__(self, content):
        self.content = content

    def __eq__(self, other):
        # Allow equality checks in tests.
        return isinstance(other, DummyMessage) and self.content == other.content


@pytest_asyncio.fixture
async def broker_instance():
    """Provides a new, launched AsyncMessageBroker instance for each test."""
    broker = AsyncMessageBroker()
    async with broker.launch():
        yield broker


def test_initialization_default():
    """Test that a new broker has valid default queues."""
    broker = AsyncMessageBroker()
    assert broker.message_queue is not None
    assert broker.response_queue is not None


def test_getstate_and_setstate():
    """Test __getstate__ and __setstate__ for pickling support."""
    broker = AsyncMessageBroker()
    state = broker.__getstate__()
    new_broker = AsyncMessageBroker()
    new_broker.__setstate__(state)
    # The queues should be identical.
    assert new_broker.message_queue is state["message_queue"]
    assert new_broker.response_queue is state["response_queue"]


@pytest.mark.asyncio
async def test_send_message_puts_message_on_queue(broker_instance: AsyncMessageBroker):
    """Test that send_message registers a pending future and places a message on the queue."""
    dummy_msg = DummyMessage("test content")
    # The broker is already launched via the fixture.
    future = broker_instance.send_message(dummy_msg)
    # Check that the returned future is an instance of BrokerMessageFuture.
    assert isinstance(future, BrokerMessageFuture)
    # There should be exactly one pending future.
    assert len(broker_instance._pending_futures) == 1

    # Retrieve the message tuple from the message queue with a short timeout.
    message_id, message = broker_instance.message_queue.get(timeout=0.1)
    # Verify that the message_id is a string and the message is our dummy message.
    assert isinstance(message_id, str)
    assert message == dummy_msg


@pytest.mark.asyncio
async def test_start_and_stop():
    """Test that launch() creates a response task and its exit cleans up properly."""
    broker = AsyncMessageBroker()
    # Start the broker via the async context manager.
    async with broker.launch():
        # Ensure that the response consumer task is running.
        assert broker._response_task is not None

        # Add a dummy future to pending futures.
        dummy_future = asyncio.Future()
        broker._pending_futures["dummy"] = dummy_future
    # After exiting the context, the broker should be cleaned up.
    assert broker._response_task is None
    assert broker._executor is None
    # Pending futures should be cleared and the dummy future cancelled.
    assert len(broker._pending_futures) == 0
    assert dummy_future.cancelled()


@pytest.mark.asyncio
async def test_consume_responses():
    """Test that a response placed in the response queue resolves the corresponding future."""
    broker = AsyncMessageBroker()
    async with broker.launch():
        test_id = "test-id"
        future = asyncio.Future()
        broker._pending_futures[test_id] = future

        # Simulate a response arriving in the response queue.
        broker.response_queue.put((test_id, "response_value"))

        # Allow some time for the background task to process the response.
        await asyncio.sleep(0.2)

        assert future.done()
        assert future.result() == "response_value"


@pytest.mark.asyncio
async def test_stop_drains_queues():
    """Test that launch() (and its exit) drains both the message and response queues."""
    broker = AsyncMessageBroker()
    # Preload queues with dummy items.
    broker.message_queue.put(("id1", "dummy_message"))
    broker.response_queue.put(("id2", "dummy_response"))

    async with broker.launch():
        # Inside the context, the broker is running.
        pass
    # After the context manager exits, the broker has been stopped, so queues should be drained.

    # Drain message_queue manually.
    drained_message_items = []
    while True:
        try:
            drained_message_items.append(broker.message_queue.get_nowait())
        except Empty:
            break
    assert drained_message_items == []

    # Drain response_queue manually.
    drained_response_items = []
    while True:
        try:
            drained_response_items.append(broker.response_queue.get_nowait())
        except Empty:
            break
    assert drained_response_items == []


@pytest.mark.asyncio
async def test_start_and_connect_server():
    """Test that start_server creates a broker and that connect_server can connect to it."""
    # Start the manager server using the async context manager.
    async with AsyncMessageBroker.start_server("localhost") as (broker, config):
        # The broker created by start_server should have valid queues.
        assert broker.message_queue is not None
        assert broker.response_queue is not None

        # Connect as a client using the provided config.
        async with AsyncMessageBroker.connect_server(config) as connected_broker:
            assert connected_broker.message_queue is not None
            # Confirm that the connected broker is an instance of AsyncMessageBroker.
            assert isinstance(connected_broker, AsyncMessageBroker)
