from functools import lru_cache
from typing import cast

from filzl import filzl as filzl_rs
from pydantic import BaseModel

from filzl.static import get_static_path


# TODO: Use a size-based cache instead of a slot-based cache
@lru_cache(maxsize=128)
def render_ssr(script: str, render_data: BaseModel) -> str:
    """
    Render the react component in the provided SSR javascript bundle. This file will
    be directly executed within the V8 runtime.

    To speed up requests for the same exact content in the same time (ie. same react and same data)
    we cache the result of the render_ssr_rust call.

    """
    polyfill_script = get_static_path("ssr_polyfills.js").read_text()
    data_json = render_data.model_dump_json()

    full_script = f"const SERVER_DATA = {data_json};\n{polyfill_script}\n{script}"

    return cast(str, filzl_rs.render_ssr(full_script))
