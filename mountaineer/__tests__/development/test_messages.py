import asyncio
from typing import Any

import pytest
import pytest_asyncio

from mountaineer.development.messages import (
    AsyncMessageBroker,
    IsolatedMessageBase,
    ReloadModulesMessage,
    ReloadResponseSuccess,
    ShutdownMessage,
)


@pytest_asyncio.fixture
async def message_broker():
    """Fixture that provides a message broker instance and handles cleanup"""
    broker = AsyncMessageBroker[IsolatedMessageBase[Any]]()
    broker.start()
    try:
        yield broker
    finally:
        await broker.stop()


@pytest.mark.asyncio
async def test_send_and_receive_message(
    message_broker: AsyncMessageBroker[IsolatedMessageBase[Any]],
) -> None:
    """Test basic message sending and receiving functionality"""
    # Create a test message
    test_message = ReloadModulesMessage(module_names=["test_module"])

    # Send the message
    future = message_broker.send_message(test_message)

    # Simulate response from another process
    response = ReloadResponseSuccess(reloaded=["test_module"], needs_restart=False)
    message_id = list(message_broker._pending_futures.keys())[0]
    message_broker.response_queue.put((message_id, response))

    # Wait for the response
    result = await asyncio.wait_for(future, timeout=1.0)

    assert isinstance(result, ReloadResponseSuccess)
    assert result.reloaded == ["test_module"]
    assert not result.needs_restart


@pytest.mark.asyncio
async def test_multiple_messages(
    message_broker: AsyncMessageBroker[IsolatedMessageBase[Any]],
) -> None:
    """Test handling multiple messages concurrently"""
    # Send multiple messages
    message1 = ReloadModulesMessage(module_names=["module1"])
    message2 = ReloadModulesMessage(module_names=["module2"])

    future1 = message_broker.send_message(message1)
    future2 = message_broker.send_message(message2)

    # Get message IDs
    message_ids = list(message_broker._pending_futures.keys())

    # Simulate responses
    response1 = ReloadResponseSuccess(reloaded=["module1"], needs_restart=False)
    response2 = ReloadResponseSuccess(reloaded=["module2"], needs_restart=False)

    message_broker.response_queue.put((message_ids[0], response1))
    message_broker.response_queue.put((message_ids[1], response2))

    # Wait for both responses
    results = await asyncio.gather(
        asyncio.wait_for(future1, timeout=1.0), asyncio.wait_for(future2, timeout=1.0)
    )

    assert isinstance(results[0], ReloadResponseSuccess)
    assert isinstance(results[1], ReloadResponseSuccess)
    assert results[0].reloaded == ["module1"]
    assert results[1].reloaded == ["module2"]


@pytest.mark.asyncio
async def test_broker_shutdown(
    message_broker: AsyncMessageBroker[IsolatedMessageBase[Any]],
) -> None:
    """Test proper broker shutdown"""
    # Send a message before shutdown
    message = ShutdownMessage()
    message_broker.send_message(message)

    # Shutdown the broker
    await message_broker.stop()

    # Verify the response task is cleaned up
    assert message_broker._response_task is None


@pytest.mark.asyncio
async def test_message_timeout(
    message_broker: AsyncMessageBroker[IsolatedMessageBase[Any]],
) -> None:
    """Test handling message timeout"""
    message = ReloadModulesMessage(module_names=["test_module"])
    future = message_broker.send_message(message)

    # Try to await the future with a short timeout
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(future, timeout=0.1)
