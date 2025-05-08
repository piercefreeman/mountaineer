import traceback
from dataclasses import dataclass, field
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
    BrokerServerConfig,
)
from mountaineer.io import async_to_sync
from mountaineer.logging import LOGGER


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
):
    CONSOLE.print("Restarting backend")
    if state.current_context is not None:
        # Drain any pending messages from the previous process
        LOGGER.debug("Draining message queue")
        jobs = await broker.drain_queue()
        if jobs:
            LOGGER.debug(f"Dropped {len(jobs)} pending messages")
        environment.stop_isolated(state.current_context)

    # We might have updated imports, so pass to the env to optionally update
    # No-op if no dependencies have changed, so the subsequent exec should be instantaneous
    environment.update_environment()

    state.current_context = environment.exec(
        run_isolated,
        isolated_context,
    )

    # Bootstrap the process and rebuild the server files
    CONSOLE.print("[bold cyan]🚀 Booting server...[/bold cyan]")
    start = time()
    await broker.send_and_get_response(BootupMessage())

    if isolated_context.webserver_config is not None:
        await broker.send_and_get_response(
            StartServerMessage(
                host=isolated_context.webserver_config.host,
                port=isolated_context.webserver_config.port,
                live_reload_port=isolated_context.webserver_config.live_reload_port,
            )
        )

    CONSOLE.print("[bold yellow]⚙️  Building useServer components...[/bold yellow]")
    await broker.send_and_get_response(BuildUseServerMessage())
    build_time = time() - start
    CONSOLE.print(
        f"[bold green]✨ Backend build complete in {build_time:.2f}s![/bold green]"
    )


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
