from pydantic import BaseModel
from filzl.ssr import SSRQueue, InputPayload
from time import time
from filzl.__tests__.fixtures import get_fixture_path
import pytest

@pytest.fixture
def ssr_worker():
    ssr_worker = SSRQueue()
    ssr_worker.ensure_valid_worker()
    yield ssr_worker
    ssr_worker.shutdown()

def test_ssr_speed_baseline(ssr_worker: SSRQueue):
    all_measurements : list[float] = []

    js_contents = get_fixture_path("home_controller_ssr_with_react.js").read_text()

    class FakeModel(BaseModel):
        pass

    for _ in range(50):
        start = time()
        ssr_worker.process_data(
            InputPayload(script=js_contents, render_data=FakeModel()),
            hard_timeout=1,
        )
        all_measurements.append(time() - start)

    assert max(all_measurements) < 0.5

# We expect an exception is raised in our thread so we don't need
# the additional log about it
@pytest.mark.filterwarnings("ignore:Exception in thread")
def test_ssr_timeout(ssr_worker: SSRQueue):
    all_measurements : list[float] = []

    js_contents = get_fixture_path("complex_controller_ssr_with_react.js").read_text()

    class FakeWaitDurationModel(BaseModel):
        # Accepts this variable to determine how many ~2s intervals to spend
        # doing synthetic work
        delay_loops: int

    start = time()
    with pytest.raises(TimeoutError):
        ssr_worker.process_data(
            InputPayload(script=js_contents, render_data=FakeWaitDurationModel(delay_loops=5)),
            hard_timeout=0.5,
        )
    assert time() - start < 1.0
