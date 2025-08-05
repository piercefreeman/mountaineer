import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import pytest
from fastapi import Depends, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from mountaineer import ControllerBase, passthrough
from mountaineer.app import AppController


# Test models
class SimpleModel(BaseModel):
    message: str
    count: int


class StreamItem(BaseModel):
    index: int
    data: str


# Mock dependency with context manager
class Database:
    def __init__(self):
        self.connected = False
        self.query_count = 0

    @asynccontextmanager
    async def connect(self):
        self.connected = True
        try:
            yield self
        finally:
            self.connected = False

    async def query(self, index: int) -> str:
        if not self.connected:
            raise RuntimeError("Database not connected")
        self.query_count += 1
        return f"db_result_{index}"


# Global database instance for testing
test_db = Database()


async def get_database():
    """Dependency that provides database connection"""
    async with test_db.connect() as db:
        yield db


class ResponseWrapperTestController(ControllerBase):
    url = "/test"
    view_path = "/test/page.tsx"

    async def render(self) -> None:
        pass

    # Test Case 1: Standard response wrapper
    @passthrough
    async def standard_action(self, name: str, count: int = 5) -> SimpleModel:
        """Standard passthrough action returning a model"""
        return SimpleModel(message=f"Hello {name}", count=count)

    # Test Case 2: SSE response wrapper without dependencies
    @passthrough
    async def stream_simple(self, limit: int = 3) -> AsyncIterator[StreamItem]:
        """Streaming endpoint without dependencies"""
        for i in range(limit):
            yield StreamItem(index=i, data=f"stream_{i}")
            await asyncio.sleep(0.01)

    # Test Case 3: SSE response wrapper with dependencies
    @passthrough
    async def stream_with_db(
        self, limit: int = 3, db: Database = Depends(get_database)
    ) -> AsyncIterator[StreamItem]:
        """Streaming endpoint with database dependency"""
        for i in range(limit):
            db_data = await db.query(i)
            yield StreamItem(index=i, data=db_data)
            await asyncio.sleep(0.01)

    # Test Case 4a: Raw response mode - standard
    @passthrough(raw_response=True)
    async def raw_standard(self, content: str) -> Response:
        """Standard endpoint returning raw response"""
        return HTMLResponse(content=f"<h1>{content}</h1>")

    # Test Case 4b: Raw response mode - SSE
    @passthrough(raw_response=True)
    async def raw_stream(self) -> Response:
        """SSE endpoint returning raw response (without dependencies for simplicity)"""

        async def generate():
            for i in range(3):
                yield f"data: raw_data_{i}\n\n"

        from fastapi.responses import StreamingResponse

        return StreamingResponse(generate(), media_type="text/event-stream")


@pytest.mark.asyncio
async def test_standard_response_wrapper():
    """Test Case 1: Standard response wrapper works correctly"""
    app = AppController(view_root=Path(__file__).parent)
    controller = ResponseWrapperTestController()
    app.register(controller)

    # Call action directly to test wrapper logic
    result = await controller.standard_action("World", count=10)

    # Verify wrapped response format
    assert result == {"passthrough": SimpleModel(message="Hello World", count=10)}


@pytest.mark.asyncio
async def test_sse_response_wrapper_simple():
    """Test Case 2: SSE response wrapper without dependencies"""
    app = AppController(view_root=Path(__file__).parent)
    controller = ResponseWrapperTestController()
    app.register(controller)

    import httpx
    from fastapi.testclient import TestClient

    with TestClient(app.app) as client:
        with httpx.Client(transport=client._transport) as httpx_client:
            with httpx_client.stream(
                "POST",
                "http://testserver/internal/api/response_wrapper_test_controller/stream_simple?limit=2",
                json={},
            ) as response:
                assert response.status_code == 200
                assert (
                    response.headers["content-type"]
                    == "text/event-stream; charset=utf-8"
                )

                items = []
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        import json

                        data = json.loads(line[6:])
                        items.append(StreamItem(**data["passthrough"]))

                assert len(items) == 2
                assert items[0] == StreamItem(index=0, data="stream_0")
                assert items[1] == StreamItem(index=1, data="stream_1")


@pytest.mark.asyncio
async def test_sse_response_wrapper_with_dependencies():
    """Test Case 3: SSE response wrapper with dependencies maintains context"""
    global test_db
    test_db = Database()

    app = AppController(view_root=Path(__file__).parent)
    controller = ResponseWrapperTestController()
    app.register(controller)

    import httpx
    from fastapi.testclient import TestClient

    with TestClient(app.app) as client:
        with httpx.Client(transport=client._transport) as httpx_client:
            with httpx_client.stream(
                "POST",
                "http://testserver/internal/api/response_wrapper_test_controller/stream_with_db?limit=3",
                json={},
            ) as response:
                assert response.status_code == 200

                items = []
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        import json

                        data = json.loads(line[6:])
                        items.append(StreamItem(**data["passthrough"]))

                # Verify all items were streamed
                assert len(items) == 3
                for i, item in enumerate(items):
                    assert item == StreamItem(index=i, data=f"db_result_{i}")

                # The key test: verify database queries were made successfully
                # This proves the context manager was active during streaming
                assert test_db.query_count == 3

    # Verify database connection was closed after streaming
    assert test_db.connected is False


@pytest.mark.asyncio
async def test_raw_response_standard():
    """Test Case 4a: Raw response mode for standard endpoint"""
    app = AppController(view_root=Path(__file__).parent)
    controller = ResponseWrapperTestController()
    app.register(controller)

    from fastapi.testclient import TestClient

    client = TestClient(app.app)

    response = client.post(
        "/internal/api/response_wrapper_test_controller/raw_standard?content=Testing"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.text == "<h1>Testing</h1>"


@pytest.mark.asyncio
async def test_raw_response_sse():
    """Test Case 4b: Raw response mode for SSE"""
    app = AppController(view_root=Path(__file__).parent)
    controller = ResponseWrapperTestController()
    app.register(controller)

    import httpx
    from fastapi.testclient import TestClient

    with TestClient(app.app) as client:
        with httpx.Client(transport=client._transport) as httpx_client:
            with httpx_client.stream(
                "POST",
                "http://testserver/internal/api/response_wrapper_test_controller/raw_stream",
                json={},
            ) as response:
                assert response.status_code == 200
                assert (
                    response.headers["content-type"]
                    == "text/event-stream; charset=utf-8"
                )

                data_items = []
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data_items.append(line[6:])

                # Verify raw SSE data format
                assert data_items == ["raw_data_0", "raw_data_1", "raw_data_2"]
