from re import sub as re_sub
from time import monotonic_ns
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from mountaineer.__tests__.fixtures import get_fixture_path
from mountaineer.ssr import V8RuntimeError, render_ssr


def test_ssr_speed_baseline():
    all_measurements: list[float] = []

    js_contents = get_fixture_path("home_controller_ssr_with_react.js").read_text()

    class FakeModel(BaseModel):
        # We need to bust the cache
        random_id: UUID

        model_config = {
            "frozen": True,
        }

    for _ in range(50):
        start = monotonic_ns()
        render_ssr(
            js_contents,
            FakeModel(random_id=uuid4()).model_dump(mode="json"),
            hard_timeout=1,
        )
        all_measurements.append((monotonic_ns() - start) / 1e9)

    assert max(all_measurements) < 0.5


# We expect an exception is raised in our thread so we don't need
# the additional log about it
def test_ssr_timeout():
    js_contents = get_fixture_path("complex_controller_ssr_with_react.js").read_text()

    class FakeWaitDurationModel(BaseModel):
        # Accepts this variable to determine how many ~2s intervals to spend
        # doing synthetic work
        delay_loops: int

        random_id: UUID

        model_config = {
            "frozen": True,
        }

    start = monotonic_ns()
    with pytest.raises(TimeoutError):
        render_ssr(
            script=js_contents,
            render_data=FakeWaitDurationModel(
                delay_loops=5, random_id=uuid4()
            ).model_dump(mode="json"),
            hard_timeout=0.5,
        )
    assert ((monotonic_ns() - start) / 1e9) < 1.0


def test_ssr_exception_context():
    """
    Ensure we report the context of V8 runtime exceptions.
    """

    class FakeModel(BaseModel):
        random_id: UUID

        model_config = {
            "frozen": True,
        }

    js_contents = """
    var SSR = {
        x: () => {
            throw new Error('custom_error_text')
        }
    };
    """

    # with pytest.raises(V8RuntimeError, match="custom_error_text"):
    try:
        render_ssr(
            script=js_contents,
            render_data=FakeModel(random_id=uuid4()).model_dump(mode="json"),
            hard_timeout=0,
        )
    except V8RuntimeError as e:
        assert re_sub(r"\s+", "", str(e)) == (
            re_sub(
                r"\s+",
                "",
                """
            Error calling function 'x': Error: custom_error_text
            Stack: Error: custom_error_text
                    at Object.x (<anonymous>:4:19)
            """,
            )
        )
