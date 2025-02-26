from inspect import getsource
from pathlib import Path
from textwrap import dedent
from typing import Any, AsyncIterator, Iterator, List, Sequence, Set, Tuple, cast

import mypy.api
import pytest
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel

from mountaineer.actions.fields import FunctionActionType, get_function_metadata
from mountaineer.actions.passthrough_dec import (
    passthrough,
)
from mountaineer.annotation_helpers import MountaineerUnsetValue
from mountaineer.app import AppController
from mountaineer.controller import ControllerBase
from mountaineer.logging import LOGGER
from mountaineer.render import RenderBase


def test_markup_passthrough():
    """
    Check that the @passthrough decorator extracts the expected
    data from our model definition.
    """

    class ExamplePassthroughModel(BaseModel):
        first_name: str

    class ExampleController(ControllerBase):
        view_path = "/test.tsx"

        @passthrough
        def get_external_data(self) -> ExamplePassthroughModel:
            return ExamplePassthroughModel(
                first_name="John",
            )

    metadata = get_function_metadata(ExampleController.get_external_data)
    assert metadata.action_type == FunctionActionType.PASSTHROUGH
    assert metadata.get_passthrough_model() == ExamplePassthroughModel
    assert metadata.function_name == "get_external_data"
    assert isinstance(metadata.reload_states, MountaineerUnsetValue)
    assert isinstance(metadata.render_model, MountaineerUnsetValue)


class ExampleRenderModel(RenderBase):
    value_a: str
    value_b: str


class ExamplePassthroughModel(BaseModel):
    status: str


class ExampleController(ControllerBase):
    url: str = "/test/{query_id}/"
    view_path = "/test.tsx"

    def __init__(self):
        super().__init__()
        self.counter = 0
        self.render_counts = 0

    def render(
        self,
        query_id: int,
    ) -> ExampleRenderModel:
        self.render_counts += 1
        return ExampleRenderModel(
            value_a="Hello",
            value_b="World",
        )

    @passthrough
    def call_passthrough(self, payload: dict) -> ExamplePassthroughModel:
        self.counter += 1
        return ExamplePassthroughModel(status="success")

    @passthrough
    async def call_passthrough_async(self, payload: dict) -> ExamplePassthroughModel:
        self.counter += 1
        return ExamplePassthroughModel(status="success")


@pytest.mark.asyncio
async def test_can_call_passthrough():
    app = AppController(view_root=Path())
    controller = ExampleController()
    app.register(controller)

    return_value_sync = await controller.call_passthrough(
        {},
    )

    return_value_async = await controller.call_passthrough_async(
        {},
    )

    # The response payload should be the same both both sync and async endpoints
    expected_response = {
        "passthrough": ExamplePassthroughModel(
            status="success",
        )
    }

    assert return_value_sync == expected_response
    assert return_value_async == expected_response

    assert controller.counter == 2

    # Our passthrough logic by definition should not re-render
    assert controller.render_counts == 0


@pytest.mark.asyncio
async def test_can_call_passthrough_original():
    """
    Ensure that we can access the raw underlying function that was
    wrapped by the decorator.

    """
    controller = ExampleController()
    assert await ExampleController.call_passthrough.original(
        controller, dict()
    ) == ExamplePassthroughModel(status="success")
    assert await ExampleController.call_passthrough_async.original(
        controller, dict()
    ) == ExamplePassthroughModel(status="success")


class ExampleModel(BaseModel):
    value: str


class ExampleIterableController(ControllerBase):
    url = "/example"
    view_path = "/test.tsx"

    async def render(self) -> None:
        pass

    @passthrough
    async def get_data(self) -> AsyncIterator[ExampleModel]:
        yield ExampleModel(value="Hello")
        yield ExampleModel(value="World")


def test_extracts_iterable():
    controller = ExampleIterableController()
    metadata = get_function_metadata(controller.get_data)
    assert metadata.passthrough_model == ExampleModel
    # Explicitly validate type here instead of using global constant
    assert metadata.media_type == "text/event-stream"


def test_disallows_invalid_iterables():
    # Sync functions
    with pytest.raises(ValueError, match="async generators are supported"):

        class ExampleController1(ControllerBase):
            @passthrough  # type: ignore
            def sync_iterable(self) -> Iterator[ExampleModel]:
                yield ExampleModel(value="Hello")
                yield ExampleModel(value="World")

    # Generator without marking up the response model
    with pytest.raises(ValueError, match="must have a response_model"):

        class ExampleController2(ControllerBase):
            @passthrough
            async def no_response_type_iterable(self) -> None:  # type: ignore
                yield ExampleModel(value="Hello")  # type: ignore
                yield ExampleModel(value="World")  # type: ignore


@pytest.mark.asyncio
async def test_can_call_iterable():
    app = AppController(view_root=Path())
    controller = ExampleIterableController()
    app.register(controller)

    # Ensure we return a valid StreamingResponse when called directly from the code
    return_value_sync = cast(Any, await controller.get_data())
    assert isinstance(return_value_sync, StreamingResponse)

    # StreamingResponses are intended to be read by an ASGI server, so we'll use the TestClient to simulate one instead of calling directly
    controller_definition = app._definition_for_controller(controller)
    passthrough_url = controller_definition.get_url_for_metadata(
        get_function_metadata(controller.get_data)
    )

    client = TestClient(app.app)
    lines: list[str] = []
    with client.stream(
        "POST",
        passthrough_url,
        json={},
    ) as response:
        for line in response.iter_lines():
            lines.append(line)

    assert lines == [
        'data: {"passthrough": {"value": "Hello"}}',
        'data: {"passthrough": {"value": "World"}}',
    ]


@pytest.mark.asyncio
async def test_raw_response():
    class ExampleController(ControllerBase):
        url: str = "/test/{query_id}/"
        view_path = "/test.tsx"

        def render(
            self,
            query_id: int,
        ) -> ExampleRenderModel:
            return ExampleRenderModel(value_a="Hello", value_b="World")

        @passthrough(raw_response=True)
        def call_passthrough(self, payload: dict) -> JSONResponse:
            return JSONResponse(content={"raw_value": "success"})

    app = AppController(view_root=Path())
    controller = ExampleController()
    app.register(controller)

    controller_definition = app._definition_for_controller(controller)

    client = TestClient(app.app)
    response = client.post(
        controller_definition.get_url_for_metadata(
            get_function_metadata(controller.call_passthrough)
        ),
        json={},
    )
    # No "passthrough" wrapping
    assert response.json() == {"raw_value": "success"}


class ExampleSequenceModel(BaseModel):
    id: int
    name: str

    def __hash__(self):
        return hash((self.id, self.name))


class ExampleSequenceController(ControllerBase):
    url = "/example-sequence"
    view_path = "/test.tsx"

    def __init__(self):
        super().__init__()

    async def render(self) -> None:
        return None

    @passthrough
    async def get_list_data(self) -> List[ExampleSequenceModel]:
        return [
            ExampleSequenceModel(id=1, name="Item 1"),
            ExampleSequenceModel(id=2, name="Item 2"),
        ]

    @passthrough  # type: ignore
    async def get_set_data(self) -> Set[ExampleSequenceModel]:
        # Note: Sets are unordered, so we can't guarantee the order of items
        return {
            ExampleSequenceModel(id=1, name="Item 1"),
            ExampleSequenceModel(id=2, name="Item 2"),
        }

    @passthrough
    async def get_tuple_data(self) -> Tuple[ExampleSequenceModel, ...]:
        return (
            ExampleSequenceModel(id=1, name="Item 1"),
            ExampleSequenceModel(id=2, name="Item 2"),
        )

    @passthrough
    async def get_sequence_data(self) -> Sequence[ExampleSequenceModel]:
        return [
            ExampleSequenceModel(id=1, name="Item 1"),
            ExampleSequenceModel(id=2, name="Item 2"),
        ]


def test_extracts_sequence():
    """
    Check that the @passthrough decorator correctly extracts the sequence model type.
    """
    metadata = get_function_metadata(ExampleSequenceController.get_list_data)
    assert metadata.action_type == FunctionActionType.PASSTHROUGH
    assert metadata.get_passthrough_model() == ExampleSequenceModel

    metadata = get_function_metadata(ExampleSequenceController.get_set_data)
    assert metadata.action_type == FunctionActionType.PASSTHROUGH
    assert metadata.get_passthrough_model() == ExampleSequenceModel

    metadata = get_function_metadata(ExampleSequenceController.get_tuple_data)
    assert metadata.action_type == FunctionActionType.PASSTHROUGH
    assert metadata.get_passthrough_model() == ExampleSequenceModel

    metadata = get_function_metadata(ExampleSequenceController.get_sequence_data)
    assert metadata.action_type == FunctionActionType.PASSTHROUGH
    assert metadata.get_passthrough_model() == ExampleSequenceModel


@pytest.mark.asyncio
async def test_can_call_sequence():
    """
    Test that we can call a passthrough function that returns a sequence of BaseModel objects.
    """
    app = AppController(view_root=Path())
    controller = ExampleSequenceController()
    app.register(controller)

    # Test list response
    list_response = await controller.get_list_data()
    assert "passthrough" in list_response
    assert isinstance(list_response["passthrough"], list)
    assert len(list_response["passthrough"]) == 2
    # Access dictionary items properly
    assert list_response["passthrough"][0]["id"] == 1  # type: ignore
    assert list_response["passthrough"][0]["name"] == "Item 1"  # type: ignore
    assert list_response["passthrough"][1]["id"] == 2  # type: ignore
    assert list_response["passthrough"][1]["name"] == "Item 2"  # type: ignore

    # Test set response
    set_response = await controller.get_set_data()
    assert "passthrough" in set_response
    assert isinstance(
        set_response["passthrough"], list
    )  # Sets are converted to lists in JSON
    assert len(set_response["passthrough"]) == 2
    # Since sets are unordered, we need to check that both items are in the response
    ids = [item["id"] for item in set_response["passthrough"]]  # type: ignore
    names = [item["name"] for item in set_response["passthrough"]]  # type: ignore
    assert 1 in ids
    assert 2 in ids
    assert "Item 1" in names
    assert "Item 2" in names

    # Test tuple response
    tuple_response = await controller.get_tuple_data()
    assert "passthrough" in tuple_response
    assert isinstance(
        tuple_response["passthrough"], list
    )  # Tuples are converted to lists in JSON
    assert len(tuple_response["passthrough"]) == 2
    assert tuple_response["passthrough"][0]["id"] == 1  # type: ignore
    assert tuple_response["passthrough"][0]["name"] == "Item 1"  # type: ignore
    assert tuple_response["passthrough"][1]["id"] == 2  # type: ignore
    assert tuple_response["passthrough"][1]["name"] == "Item 2"  # type: ignore

    # Test sequence response
    sequence_response = await controller.get_sequence_data()
    assert "passthrough" in sequence_response
    assert isinstance(sequence_response["passthrough"], list)
    assert len(sequence_response["passthrough"]) == 2
    assert sequence_response["passthrough"][0]["id"] == 1  # type: ignore
    assert sequence_response["passthrough"][0]["name"] == "Item 1"  # type: ignore
    assert sequence_response["passthrough"][1]["id"] == 2  # type: ignore
    assert sequence_response["passthrough"][1]["name"] == "Item 2"  # type: ignore


@pytest.mark.parametrize(
    "passthrough_value, return_typehint, return_value, is_valid",
    [
        # Normal return type
        ("@passthrough", "InputModel", "return InputModel()", True),
        (
            "@passthrough(exception_models=[])",
            "InputModel",
            "return InputModel()",
            True,
        ),
        # Raw responses have to be fastapi.Response models or subclasses
        ("@passthrough(raw_response=True)", "InputModel", "return InputModel()", False),
        (
            "@passthrough(raw_response=True)",
            "JSONResponse",
            "return JSONResponse(content={})",
            True,
        ),
        (
            "@passthrough(raw_response=True)",
            "HTMLResponse",
            'return HTMLResponse(content="TEST")',
            True,
        ),
        # We can return JSONResponse is normal passthrough functions as well, because they'll be wrapped
        # in a passthrough response
        # We can't return other fastapi.Response models, however
        ("@passthrough", "JSONResponse", "return JSONResponse(content={})", True),
        ("@passthrough", "HTMLResponse", 'return HTMLResponse(content="TEST")', False),
        # Iterator types are only allowed if they're async
        ("@passthrough", "AsyncIterator[InputModel]", "yield InputModel()", True),
        # Sequence types are allowed
        ("@passthrough", "List[InputModel]", "return [InputModel()]", True),
        # Set test is skipped because pydantic models are not hashable by default in the mypy test
        # ("@passthrough", "Set[InputModel]", "return {InputModel()}", True),
        ("@passthrough", "Tuple[InputModel, ...]", "return (InputModel(),)", True),
        ("@passthrough", "Sequence[InputModel]", "return [InputModel()]", True),
    ],
)
def test_passthrough_typechecking(
    passthrough_value: str,
    return_typehint: str,
    return_value: str,
    is_valid: bool,
    tmp_path: Path,
):
    """
    Ensure that mypy will catch type errors in passthrough signatures

    """

    def run_function():
        from typing import AsyncIterator, List, Sequence, Set, Tuple  # noqa: F401

        from fastapi.responses import HTMLResponse, JSONResponse  # noqa: F401
        from pydantic import BaseModel  # noqa: F401

        from mountaineer import ControllerBase, passthrough  # noqa: F401

        class InputModel(BaseModel):
            pass

            def __hash__(self):
                return hash(id(self))

        class TestController:
            @passthrough  # type: ignore
            async def get_external_data(self) -> str:
                return "{output_value}"

    # Ignore the "run_function()" function header itself
    function_lines = getsource(run_function).split("\n")[1:]
    value = dedent("\n".join(function_lines))

    value = value.replace("@passthrough", passthrough_value)
    value = value.replace("-> str", f"-> {return_typehint}")
    value = value.replace('return "{output_value}"', return_value)
    value = value.replace("# type: ignore", "")

    LOGGER.debug(f"Input value:\n{value}")

    module_path = tmp_path / "test.py"
    module_path.write_text(value)

    result = mypy.api.run([str(module_path)])
    LOGGER.debug(f"mypy result: {result}")

    if is_valid:
        assert "Success" in result[0]
    else:
        assert "error" in result[0]
