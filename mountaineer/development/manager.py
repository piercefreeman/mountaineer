import traceback
from dataclasses import dataclass, field
from os import getenv
from pathlib import Path
from time import time

from firehot import Environment
from firehot.environment import IsolatedProcess

from mountaineer.console import CONSOLE
from mountaineer.development.isolation import IsolatedAppContext
from mountaineer.development.messages import (
    BootupMessage,
    BuildJsMessage,
    BuildUseServerMessage,
    StartServerMessage,
)
from mountaineer.development.messages_broker import (
    AsyncMessageBroker,
    BrokerExecutionError,
    BrokerServerConfig,
    BrokerTimeoutError,
)
from mountaineer.io import async_to_sync
from mountaineer.logging import LOGGER

DEFAULT_RESTART_MESSAGE_TIMEOUT = 5.0
DEFAULT_RESTART_ATTEMPTS = 2


@dataclass
class FileChangesState:
    pending_js: set[Path] = field(default_factory=set)
    pending_python: set[Path] = field(default_factory=set)

    current_context: IsolatedProcess | None = None


@dataclass
class WebserverConfig:
    host: str
    port: int
    live_reload_port: int


@dataclass
class IsolatedContext:
    webcontroller: str
    webserver_config: WebserverConfig | None
    message_config: BrokerServerConfig


@async_to_sync
async def run_isolated(
    isolated_context: IsolatedContext,
):
    """
    Isolated subprocess with all runtime modules already injected by firehot.

    """
    app_context = IsolatedAppContext.from_webcontroller(
        webcontroller=isolated_context.webcontroller,
    )

    try:
        async with AsyncMessageBroker.new_client(
            isolated_context.message_config
        ) as broker:
            await app_context.run_async(broker)
    except Exception as e:
        # This logging should happen automatically
        CONSOLE.print(f"[red]Error: {e}")
        CONSOLE.print(traceback.format_exc())
        raise e


async def restart_backend(
    environment: Environment,
    broker: AsyncMessageBroker,
    state: FileChangesState,
    isolated_context: IsolatedContext,
    *,
    message_timeout: float | None = None,
    attempts: int | None = None,
):
    message_timeout = (
        message_timeout
        if message_timeout is not None
        else _get_float_env(
            "MOUNTAINEER_RESTART_MESSAGE_TIMEOUT",
            DEFAULT_RESTART_MESSAGE_TIMEOUT,
        )
    )
    attempts = (
        attempts
        if attempts is not None
        else _get_int_env("MOUNTAINEER_RESTART_ATTEMPTS", DEFAULT_RESTART_ATTEMPTS)
    )
    attempts = max(1, attempts)

    last_timeout: BrokerTimeoutError | None = None
    for attempt in range(attempts):
        CONSOLE.print("Restarting backend")
        if attempt > 0:
            LOGGER.warning(
                "Retrying backend restart after isolated process timeout "
                f"({attempt + 1}/{attempts})"
            )

        await _stop_current_context(environment, broker, state)

        # We might have updated imports, so pass to the env to optionally update.
        # No-op if no dependencies have changed, so the subsequent exec should be instantaneous.
        environment.update_environment()

        state.current_context = environment.exec(
            run_isolated,
            isolated_context,
        )

        try:
            await _bootstrap_backend(
                broker,
                isolated_context,
                message_timeout=message_timeout,
            )
            return
        except BrokerTimeoutError as e:
            last_timeout = e
            LOGGER.warning(f"Isolated backend restart timed out: {e}")
            await _stop_current_context(environment, broker, state)

    raise BrokerExecutionError(
        f"Timed out restarting backend after {attempts} attempts: {last_timeout}",
        "",
    )


async def _stop_current_context(
    environment: Environment,
    broker: AsyncMessageBroker,
    state: FileChangesState,
):
    if state.current_context is not None:
        # Drain any pending messages from the previous process
        LOGGER.debug("Draining message queue")
        jobs = await broker.drain_queue()
        if jobs:
            LOGGER.debug(f"Dropped {len(jobs)} pending messages")
        environment.stop_isolated(state.current_context)
        state.current_context = None


async def _bootstrap_backend(
    broker: AsyncMessageBroker,
    isolated_context: IsolatedContext,
    *,
    message_timeout: float,
):
    # Bootstrap the process and rebuild the server files
    CONSOLE.print("[bold cyan]🚀 Booting server...[/bold cyan]")
    start = time()
    await broker.send_and_get_response(BootupMessage(), timeout=message_timeout)

    if isolated_context.webserver_config is not None:
        await broker.send_and_get_response(
            StartServerMessage(
                host=isolated_context.webserver_config.host,
                port=isolated_context.webserver_config.port,
                live_reload_port=isolated_context.webserver_config.live_reload_port,
            ),
            timeout=message_timeout,
        )

    CONSOLE.print("[bold yellow]⚙️  Building useServer components...[/bold yellow]")
    await broker.send_and_get_response(
        BuildUseServerMessage(), timeout=message_timeout
    )
    build_time = time() - start
    CONSOLE.print(
        f"[bold green]✨ Backend build complete in {build_time:.2f}s![/bold green]"
    )


def _get_float_env(name: str, default: float) -> float:
    raw_value = getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        LOGGER.warning(f"Invalid {name}={raw_value!r}; using {default}")
        return default


def _get_int_env(name: str, default: int) -> int:
    raw_value = getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        LOGGER.warning(f"Invalid {name}={raw_value!r}; using {default}")
        return default


async def rebuild_frontend(broker: AsyncMessageBroker, state: FileChangesState):
    start = time()
    CONSOLE.print("[bold yellow]🔨 Rebuilding frontend...[/bold yellow]")

    await broker.send_and_get_response(
        # None will rebuild everything - we want this in cases where we are called
        # without a list provided
        BuildJsMessage(updated_js=list(state.pending_js) if state.pending_js else None)
    )

    build_time = time() - start
    CONSOLE.print(
        f"[bold green]✨ Frontend build complete in {build_time:.2f}s![/bold green]"
    )
