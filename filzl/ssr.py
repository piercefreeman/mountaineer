from functools import lru_cache
from time import time
from typing import cast

from pydantic import BaseModel

from filzl import filzl as filzl_rs  # type: ignore
from filzl.static import get_static_path


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

    polyfill_script = get_static_path("ssr_polyfills.js").read_text()
    data_json = render_data.model_dump_json()

    full_script = f"const SERVER_DATA = {data_json};\n{polyfill_script}\n{script}"

    try:
        # Convert to milliseconds for the rust worker
        render_result = filzl_rs.render_ssr(
            full_script, int(hard_timeout * 1000) if hard_timeout else 0
        )
    except ValueError:
        raise TimeoutError("SSR render was interrupted after hard timeout")

    return cast(str, render_result)
