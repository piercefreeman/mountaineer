import asyncio
from typing import Literal

from pydantic import BaseModel


class ServerConfig(BaseModel):
    host: str
    port: int


class RuntimePayload(BaseModel):
    schema_version: Literal[1]
    mode: Literal["development", "production"]
    generation: int
    rebuild_generated: bool = True
    webcontroller: str
    server: ServerConfig
    dev_server_origin: str | None = None


_runtime_payload: RuntimePayload | None = None


def set_runtime_payload(payload: RuntimePayload | None) -> None:
    global _runtime_payload
    _runtime_payload = payload


def get_runtime_payload() -> RuntimePayload | None:
    return _runtime_payload


def serve_runtime(payload: RuntimePayload) -> None:
    set_runtime_payload(payload)
    controller = asyncio.run(_prepare_controller(payload))

    import uvicorn

    uvicorn.run(
        controller.app,
        host=payload.server.host,
        port=payload.server.port,
        reload=False,
        access_log=False,
        log_level="warning",
    )


async def _prepare_controller(payload: RuntimePayload):
    from mountaineer.development.isolation import IsolatedAppContext

    context = IsolatedAppContext.from_webcontroller(
        payload.webcontroller,
        use_dev_exceptions=payload.mode == "development",
    )
    await context.initialize_app_state()
    if context.app_controller is None:
        raise RuntimeError("App controller did not initialize")

    if payload.mode == "development" and payload.rebuild_generated:
        if context.js_compiler is None:
            raise RuntimeError("Development compiler did not initialize")
        await context.js_compiler.build_use_server()

    return context.app_controller


def build_generated(payload: RuntimePayload) -> None:
    set_runtime_payload(payload)
    asyncio.run(_prepare_controller(payload))
