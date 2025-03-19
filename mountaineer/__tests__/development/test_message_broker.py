import asyncio
import multiprocessing
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio

from mountaineer.development.messages import IsolatedMessageBase, MessageTypes
from mountaineer.development.messages_broker import (
    AsyncMessageBroker,
    BrokerAuthenticationError,
    BrokerServerConfig,
    OKResponse,
)


@dataclass
class DummyMessage(IsolatedMessageBase):
    content: str

    def __eq__(self, other):
        # Allow equality checks in tests.
        return isinstance(other, DummyMessage) and self.content == other.content


@pytest_asyncio.fixture
async def broker_pair():
    """
    Provides a connected pair of brokers - a server broker and client broker.
    This simulates the typical usage pattern of the broker system.
    """
    async with AsyncMessageBroker.start_server() as (server_broker, config):
        async with AsyncMessageBroker.new_client(config) as client_broker:
            yield server_broker, client_broker


@pytest.mark.asyncio
async def test_basic_job_flow(
    broker_pair: tuple[AsyncMessageBroker, AsyncMessageBroker],
):
    """Test the basic job flow between server and client brokers."""
    server_broker, client_broker = broker_pair

    # Send a job from server
    job_data = {"message": "test content"}
    job_id = "test-job-1"
    response = await server_broker.send_job(job_id, job_data)
    assert isinstance(response, OKResponse)

    # Client gets the job and sends response
    response_data = {"processed": True}
    await client_broker.send_response(job_id, response_data)

    # Server gets the response
    result = await server_broker.get_response(job_id)
    assert result == response_data


@pytest.mark.asyncio
async def test_auth_validation(
    broker_pair: tuple[AsyncMessageBroker, AsyncMessageBroker],
):
    """Test that authentication is properly enforced."""
    server_broker, _ = broker_pair

    # Create client with invalid auth
    invalid_config = BrokerServerConfig[MessageTypes](
        host=server_broker.host, port=server_broker.port, auth_key="invalid_key"
    )

    async with AsyncMessageBroker.new_client(invalid_config) as invalid_client:
        # Try to send a job with invalid auth
        with pytest.raises(BrokerAuthenticationError):
            await invalid_client.send_job("test-job", {"data": "test"})

        # Try to send a response with invalid auth
        with pytest.raises(BrokerAuthenticationError):
            await invalid_client.send_response("test-job", {"data": "test"})

        # Try to get a response with invalid auth
        with pytest.raises(BrokerAuthenticationError):
            await invalid_client.get_response("test-job")


@pytest.mark.asyncio
async def test_complex_object_serialization(
    broker_pair: tuple[AsyncMessageBroker, AsyncMessageBroker],
):
    """Test that complex Python objects can be sent through the broker."""
    server_broker, client_broker = broker_pair

    complex_data = {"numbers": [1, 2, 3], "nested": {"key": ["value1", "value2"]}}
    job_id = "complex-job"

    # Send complex job
    response = await server_broker.send_job(job_id, complex_data)
    assert isinstance(response, OKResponse)

    # Send complex response
    complex_response = {"processed": True, "data": [1, 2, 3]}
    await client_broker.send_response(job_id, complex_response)

    # Verify response
    result = await server_broker.get_response(job_id)
    assert result == complex_response


@pytest.mark.asyncio
async def test_multiple_jobs(
    broker_pair: tuple[AsyncMessageBroker, AsyncMessageBroker],
):
    """Test handling multiple jobs in sequence."""
    server_broker, client_broker = broker_pair

    # Send multiple jobs
    job_ids = [f"job-{i}" for i in range(3)]
    job_data = [{"message": f"message{i}"} for i in range(3)]

    # Send all jobs
    for job_id, data in zip(job_ids, job_data):
        response = await server_broker.send_job(job_id, data)
        assert isinstance(response, OKResponse)

    # Process all jobs
    for i, job_id in enumerate(job_ids):
        await client_broker.send_response(job_id, f"response{i}")

    # Verify all responses
    results = await asyncio.gather(
        *[server_broker.get_response(job_id) for job_id in job_ids]
    )
    assert results == ["response0", "response1", "response2"]


@pytest.mark.asyncio
async def test_nonexistent_job():
    """Test getting response for a nonexistent job."""
    async with AsyncMessageBroker.start_server() as (server_broker, config):
        async with AsyncMessageBroker.new_client(config) as client_broker:
            # Try to get response for non-existent job
            # This should create a future that waits for the response
            get_response_task = asyncio.create_task(
                server_broker.get_response("nonexistent-job")
            )

            # Send response for the job
            await client_broker.send_response("nonexistent-job", "late response")

            # Now the get_response should complete
            result = await get_response_task
            assert result == "late response"


@pytest.mark.asyncio
async def test_concurrent_clients():
    """Test multiple clients can interact with the same server."""
    async with AsyncMessageBroker.start_server() as (server_broker, config):
        async with (
            AsyncMessageBroker.new_client(config) as client1,
            AsyncMessageBroker.new_client(config) as client2,
        ):
            # Client 1 handles job1
            await server_broker.send_job("job1", "data1")
            await client1.send_response("job1", "response1")

            # Client 2 handles job2
            await server_broker.send_job("job2", "data2")
            await client2.send_response("job2", "response2")

            # Verify responses
            assert await server_broker.get_response("job1") == "response1"
            assert await server_broker.get_response("job2") == "response2"


async def run_client_process(
    config: BrokerServerConfig, job_id: str, response_data: Any
):
    """
    Async function to run inside a client process.
    """
    async with AsyncMessageBroker.new_client(config) as client:
        await client.send_response(job_id, response_data)


def client_process_entrypoint(config_dict: dict, job_id: str, response_data: Any):
    """
    Synchronous entry point for client process.
    """
    config = BrokerServerConfig[MessageTypes](**config_dict)
    asyncio.run(run_client_process(config, job_id, response_data))


@pytest.mark.asyncio
async def test_real_process_communication():
    """Test communication between real separate processes."""
    async with AsyncMessageBroker.start_server() as (server_broker, config):
        # Convert config to dict for pickling
        config_dict = {
            "host": config.host,
            "port": config.port,
            "auth_key": config.auth_key,
        }

        # Create and start client process
        process = multiprocessing.Process(
            target=client_process_entrypoint,
            args=(config_dict, "test-job", "process-response"),
        )
        process.start()

        # Send job from server
        response = await server_broker.send_job("test-job", {"data": "test"})
        assert isinstance(response, OKResponse)

        # Wait for response from client process
        result = await server_broker.get_response("test-job")
        assert result == "process-response"

        # Clean up process
        process.join()
        assert process.exitcode == 0


@pytest.mark.asyncio
async def test_multiple_process_clients():
    """Test multiple client processes interacting with the server."""
    async with AsyncMessageBroker.start_server() as (server_broker, config):
        config_dict = {
            "host": config.host,
            "port": config.port,
            "auth_key": config.auth_key,
        }

        # Create multiple client processes
        processes = []
        job_ids = [f"job-{i}" for i in range(3)]
        responses = [f"process-response-{i}" for i in range(3)]

        for job_id, response in zip(job_ids, responses):
            process = multiprocessing.Process(
                target=client_process_entrypoint, args=(config_dict, job_id, response)
            )
            process.start()
            processes.append(process)

        # Send jobs from server
        for job_id in job_ids:
            response = await server_broker.send_job(job_id, {"data": job_id})
            assert isinstance(response, OKResponse)

        # Get all responses
        results = await asyncio.gather(
            *[server_broker.get_response(job_id) for job_id in job_ids]
        )
        assert results == responses

        # Clean up processes
        for process in processes:
            process.join()
            assert process.exitcode == 0


@pytest.mark.asyncio
async def test_process_reconnection():
    """
    Test the edge case where:
    - A job is processed by one client process
    - That process exits
    - A new job is processed by a new client process
    """
    async with AsyncMessageBroker.start_server() as (server_broker, config):
        config_dict = {
            "host": config.host,
            "port": config.port,
            "auth_key": config.auth_key,
        }

        # First client process
        process1 = multiprocessing.Process(
            target=client_process_entrypoint, args=(config_dict, "job1", "response1")
        )
        process1.start()

        # Send first job
        await server_broker.send_job("job1", "data1")
        result1 = await server_broker.get_response("job1")
        assert result1 == "response1"
        process1.join()
        assert process1.exitcode == 0

        # Second client process
        process2 = multiprocessing.Process(
            target=client_process_entrypoint, args=(config_dict, "job2", "response2")
        )
        process2.start()

        # Send second job
        await server_broker.send_job("job2", "data2")
        result2 = await server_broker.get_response("job2")
        assert result2 == "response2"
        process2.join()
        assert process2.exitcode == 0


def error_client_entrypoint(config_dict: dict):
    async def main():
        config = BrokerServerConfig[MessageTypes](**config_dict)
        async with AsyncMessageBroker.new_client(config) as client:
            # Simulate an error by trying to send response for non-existent job
            await client.send_response("nonexistent", "error")

    asyncio.run(main())


@pytest.mark.asyncio
async def test_process_error_handling():
    """Test handling of client process errors."""

    async with AsyncMessageBroker.start_server() as (server_broker, config):
        config_dict = {
            "host": config.host,
            "port": config.port,
            "auth_key": config.auth_key,
        }

        # Start error process
        process = multiprocessing.Process(
            target=error_client_entrypoint, args=(config_dict,)
        )
        process.start()
        process.join()

        # Process should exit cleanly even after error
        assert process.exitcode == 0


def worker_process(config_dict: dict):
    async def main():
        config = BrokerServerConfig[MessageTypes](**config_dict)
        async with AsyncMessageBroker.new_client(config) as client:
            # Get a job and send a response
            job_id, job_data = await client.get_job()
            await client.send_response(job_id, f"processed-{job_data['task']}")

    asyncio.run(main())


@pytest.mark.asyncio
async def test_get_job_process():
    """Test get_job functionality with real processes."""
    async with AsyncMessageBroker.start_server() as (server_broker, config):
        config_dict = {
            "host": config.host,
            "port": config.port,
            "auth_key": config.auth_key,
        }

        # Start worker process
        process = multiprocessing.Process(target=worker_process, args=(config_dict,))
        process.start()

        # Send a job
        await server_broker.send_job("test-job", {"task": "test-task"})

        # Wait for response
        response = await server_broker.get_response("test-job")
        assert response == "processed-test-task"

        # Clean up process
        process.join()
        assert process.exitcode == 0


@pytest.mark.asyncio
async def test_multiple_waiting_clients():
    """Test multiple clients waiting for jobs."""
    async with AsyncMessageBroker.start_server() as (server_broker, config):
        async with (
            AsyncMessageBroker.new_client(config) as client1,
            AsyncMessageBroker.new_client(config) as client2,
        ):
            # Start both clients waiting for jobs
            task1 = asyncio.create_task(client1.get_job())
            task2 = asyncio.create_task(client2.get_job())

            # Small delay to ensure both clients are waiting
            await asyncio.sleep(0.1)

            # Send two jobs
            await server_broker.send_job("job1", {"task": "task1"})
            await server_broker.send_job("job2", {"task": "task2"})

            # Get results from both clients
            results = await asyncio.gather(task1, task2)

            # Verify each job was received exactly once
            job_ids = {result[0] for result in results}
            assert job_ids == {"job1", "job2"}
