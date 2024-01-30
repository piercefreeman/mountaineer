from typing import cast

from filzl_rs import render_ssr as render_ssr_rust
from pydantic import BaseModel

from filzl.static import get_static_path


def render_ssr(script: str, render_data: BaseModel) -> str:
    """
    Render the react component in the provided SSR javascript bundle. This file will
    be directly executed within the V8 runtime.
    """
    polyfill_script = get_static_path("ssr_polyfills.js").read_text()
    data_json = render_data.model_dump_json()

    full_script = f"const SERVER_DATA = {data_json};\n{polyfill_script}\n{script}"

    return cast(str, render_ssr_rust(full_script))
