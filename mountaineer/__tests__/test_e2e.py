from pathlib import Path
from typing import Any, Dict, List, cast

import pytest
from pydantic import BaseModel

from mountaineer import AppController, ControllerBase, passthrough
from mountaineer.render import RenderBase


@pytest.mark.asyncio
async def test_passthrough_sequence_response():
    """
    Test that the passthrough decorator correctly handles sequence responses
    and generates the appropriate TypeScript types.
    """

    # Define a simple model for the test
    class Item(BaseModel):
        id: int
        name: str

    # Create a controller with a passthrough action that returns a sequence
    class SequenceController(ControllerBase):
        url = "/api/sequence"
        view_path = "/sequence.tsx"

        def __init__(self):
            super().__init__()

        def render(self) -> RenderBase:
            return RenderBase()

        @passthrough
        async def get_items(self) -> List[Item]:
            """Return a list of items."""
            return [
                Item(id=1, name="Item 1"),
                Item(id=2, name="Item 2"),
            ]

    # Create the app and register the controller
    app = AppController(view_root=Path())
    controller = SequenceController()
    app.register(controller)

    # Call the action and verify the response
    response = await controller.get_items()
    assert "passthrough" in response
    passthrough_data = response["passthrough"]
    assert isinstance(passthrough_data, list)
    assert len(passthrough_data) == 2

    # The response data is serialized to JSON, so we need to access it as dictionaries
    # Use cast to tell the type checker these are dictionaries
    items = cast(List[Dict[str, Any]], passthrough_data)

    assert items[0]["id"] == 1
    assert items[0]["name"] == "Item 1"
    assert items[1]["id"] == 2
    assert items[1]["name"] == "Item 2"

    # Verify TypeScript types would be generated correctly
    # We don't need to actually build the TypeScript files for this test
    from mountaineer.client_builder.interface_builders.action import ActionInterface
    from mountaineer.client_builder.parser import ControllerParser

    # Parse the controller
    parser = ControllerParser()
    controller_wrapper = parser.parse_controller(SequenceController)

    # Get the action wrapper for get_items
    action_wrapper = controller_wrapper.actions["get_items"]

    # Create the interface
    action_interface = ActionInterface.from_action(
        action_wrapper, "/api/sequence", SequenceController
    )

    # The response type is wrapped in a GetItemsResponseWrapped interface
    # which internally contains the Item[] array
    assert "Promise<GetItemsResponseWrapped>" in action_interface.response_type
