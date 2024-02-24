from re import finditer as re_finditer
from typing import cast

from pydantic import BaseModel

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.cache import extended_lru_cache
from mountaineer.static import get_static_path


class V8RuntimeError(Exception):
    pass


def fix_exception_lines(*, exception: str, injected_script: str):
    """
    Since we create a synthetic script to run in the V8 runtime, the line numbers
    of the in-application stack trace will be offset by however long our
    injected script is. This function re-processed the stack trace to fix the
    line number.

    """
    offset_lines = injected_script.count("\n")

    text_replacements: dict[tuple[int, int], str] = {}
    for match in re_finditer(r"\(([<>A-Za-z0-9]+?):(\d+?):(\d+?)\)", exception):
        # Only replace the line numbers
        text_replacements[match.span(2)] = str(int(match.group(2)) - offset_lines)

    sorted_replacements = sorted(
        text_replacements.items(), key=lambda x: x[0][0], reverse=True
    )

    for (start, end), replacement in sorted_replacements:
        exception = exception[:start] + replacement + exception[end:]

    return exception


@extended_lru_cache(maxsize=128, max_size_mb=5)
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

    injected_script = f"const SERVER_DATA = {data_json};\n{polyfill_script}\n"
    full_script = f"{injected_script}{script}"

    try:
        # Convert to milliseconds for the rust worker
        render_result = mountaineer_rs.render_ssr(
            full_script, int(hard_timeout * 1000) if hard_timeout else 0
        )
    except ConnectionAbortedError:
        raise TimeoutError("SSR render was interrupted after hard timeout")
    except ValueError as e:
        raise V8RuntimeError(
            fix_exception_lines(exception=str(e), injected_script=injected_script)
        )

    return cast(str, render_result)
