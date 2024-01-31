from functools import lru_cache
from typing import cast

from pydantic import BaseModel

from filzl import filzl as filzl_rs  # type: ignore
from filzl.static import get_static_path
from filzl.timeout_worker import TimedWorkerQueue


class InputPayload(BaseModel):
    script: str
    render_data: BaseModel


class SSRQueue(TimedWorkerQueue[InputPayload, str]):
    @staticmethod
    def run(element: InputPayload) -> str:
        polyfill_script = get_static_path("ssr_polyfills.js").read_text()
        data_json = element.render_data.model_dump_json()

        full_script = (
            f"const SERVER_DATA = {data_json};\n{polyfill_script}\n{element.script}"
        )

        return cast(str, filzl_rs.render_ssr(full_script))


SSR_WORKER = SSRQueue()


# TODO: Use a size-based cache instead of a slot-based cache
@lru_cache(maxsize=128)
def render_ssr(
    script: str, render_data: BaseModel, hard_timeout: int | float | None = None
) -> str:
    """
    Render the react component in the provided SSR javascript bundle. This file will
    be directly executed within the V8 runtime.

    To speed up requests for the same exact content in the same time (ie. same react and same data)
    we cache the result of the render_ssr_rust call.

    :raises TimeoutError: If the render takes longer than the hard_timeout

    """
    payload = InputPayload(
        script=script,
        render_data=render_data,
    )

    # If we don't have a timeout, we don't need to run in a separate process
    if not hard_timeout:
        return SSR_WORKER.run(payload)

    return SSR_WORKER.process_data(
        payload,
        hard_timeout=hard_timeout,
    )
