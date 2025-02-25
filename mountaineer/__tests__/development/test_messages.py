import asyncio
from typing import Any

import pytest
import pytest_asyncio

from mountaineer.development.messages import (
    AsyncMessageBroker,
    BuildJsMessage,
    IsolatedMessageBase,
    ReloadModulesMessage,
    ReloadResponse,
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
    response = ReloadResponse(
        success=True, reloaded=["test_module"], needs_restart=False
    )
    message_id = list(message_broker._pending_futures.keys())[0]
    message_broker.response_queue.put((message_id, response))

    # Wait for the response
    result = await asyncio.wait_for(future, timeout=1.0)

    assert isinstance(result, ReloadResponse)
    assert result.success == True
    assert result.reloaded == ["test_module"]
    assert result.needs_restart == False


@pytest.mark.asyncio
async def test_multiple_messages(
    message_broker: AsyncMessageBroker[IsolatedMessageBase[Any]],
) -> None:
    """Test handling multiple messages concurrently"""
    # Send multiple messages
    message1 = ReloadModulesMessage(module_names=["module1"])
    message2 = BuildJsMessage()

    future1 = message_broker.send_message(message1)
    future2 = message_broker.send_message(message2)

    # Get message IDs
    message_ids = list(message_broker._pending_futures.keys())

    # Simulate responses
    response1 = ReloadResponse(success=True, reloaded=["module1"], needs_restart=False)
    message_broker.response_queue.put((message_ids[0], response1))

    message_broker.response_queue.put((message_ids[1], None))

    # Wait for both responses
    results = await asyncio.gather(
        asyncio.wait_for(future1, timeout=1.0), asyncio.wait_for(future2, timeout=1.0)
    )

    assert isinstance(results[0], ReloadResponse)
    assert results[0].success == True
    assert results[1] is None


@pytest.mark.asyncio
async def test_broker_shutdown(
    message_broker: AsyncMessageBroker[IsolatedMessageBase[Any]],
) -> None:
    """Test proper broker shutdown"""
    # Send a message before shutdown
    message = ShutdownMessage()
    future = message_broker.send_message(message)

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
