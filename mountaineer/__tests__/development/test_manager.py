import pytest

from mountaineer.development.manager import (
    FileChangesState,
    IsolatedContext,
    WebserverConfig,
    restart_backend,
)
from mountaineer.development.messages import (
    BootupMessage,
    BuildUseServerMessage,
    StartServerMessage,
)
from mountaineer.development.messages_broker import (
    BrokerExecutionError,
    BrokerServerConfig,
    BrokerTimeoutError,
)


class FakeProcess:
    pass


class FakeEnvironment:
    def __init__(self):
        self.started: list[FakeProcess] = []
        self.stopped: list[FakeProcess] = []
        self.update_count = 0

    def update_environment(self):
        self.update_count += 1

    def exec(self, *_args, **_kwargs):
        process = FakeProcess()
        self.started.append(process)
        return process

    def stop_isolated(self, process: FakeProcess):
        self.stopped.append(process)


class FakeBroker:
    def __init__(self, boot_timeouts: int):
        self.boot_timeouts = boot_timeouts
        self.calls: list[tuple[type, float | None]] = []
        self.drain_count = 0

    async def drain_queue(self):
        self.drain_count += 1
        return []

    async def send_and_get_response(self, message, timeout=None):
        self.calls.append((type(message), timeout))
        if isinstance(message, BootupMessage) and self.boot_timeouts:
            self.boot_timeouts -= 1
            raise BrokerTimeoutError("boot timeout")
        return object()


def isolated_context():
    return IsolatedContext(
        webcontroller="ci_webapp.app:controller",
        webserver_config=WebserverConfig(
            host="127.0.0.1",
            port=5006,
            live_reload_port=5007,
        ),
        message_config=BrokerServerConfig(
            host="127.0.0.1",
            port=1,
            auth_key="test",
        ),
    )


@pytest.mark.asyncio
async def test_restart_backend_retries_timed_out_boot():
    environment = FakeEnvironment()
    broker = FakeBroker(boot_timeouts=1)
    state = FileChangesState()

    await restart_backend(
        environment,  # type: ignore[arg-type]
        broker,  # type: ignore[arg-type]
        state,
        isolated_context(),
        message_timeout=0.01,
        attempts=2,
    )

    assert environment.update_count == 2
    assert environment.started == [environment.stopped[0], state.current_context]
    assert state.current_context is environment.started[1]
    assert broker.calls == [
        (BootupMessage, 0.01),
        (BootupMessage, 0.01),
        (StartServerMessage, 0.01),
        (BuildUseServerMessage, 0.01),
    ]


@pytest.mark.asyncio
async def test_restart_backend_stops_context_after_exhausting_timeouts():
    environment = FakeEnvironment()
    broker = FakeBroker(boot_timeouts=2)
    state = FileChangesState()

    with pytest.raises(BrokerExecutionError):
        await restart_backend(
            environment,  # type: ignore[arg-type]
            broker,  # type: ignore[arg-type]
            state,
            isolated_context(),
            message_timeout=0.01,
            attempts=2,
        )

    assert environment.started == environment.stopped
    assert state.current_context is None
