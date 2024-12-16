from json import dumps as json_dumps
from re import finditer as re_finditer
from typing import Any, cast

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.cache import extended_lru_cache
from mountaineer.client_compiler.source_maps import SourceMapParser
from mountaineer.static import get_static_path


class V8RuntimeError(Exception):
    """
    An exception thrown by the V8 runtime in the case of a permanent failure that
    involves the content of the script.

    """

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
    script: str,
    render_data: dict[str, Any],
    hard_timeout: int | float | None = None,
    sourcemap: str | None = None,
) -> str:
    """
    Render the React component in the provided SSR javascript bundle. This file will
    be directly executed within the V8 runtime.

    To speed up requests for the same exact content (ie. same react and same data)
    we cache the result of the render_ssr_rust call by default for a limited amount of
    previous calls. We limit the overall size of this cache to 5MB.

    :param script: The raw code of the javascript bundle to execute. Should be pre-compiled into an
        SSR compatible package with a single entrypoint.
    :param render_data: The data to inject into the SSR javascript bundle
    :param hard_timeout: The maximum time to allow the render to take in seconds. If the render takes
        longer than this time, our thread supervisor will kick in and terminate the rust worker.

    :raises TimeoutError: If the render takes longer than the hard_timeout
    :raises V8RuntimeError: If the V8 runtime throws an exception during the render

    """
    polyfill_script = get_static_path("ssr_polyfills.js").read_text()
    data_json = json_dumps(render_data)

    injected_script = f"var SERVER_DATA = {data_json};\n{polyfill_script}\n"
    full_script = f"{injected_script}{script}"

    try:
        # Convert to milliseconds for the rust worker
        render_result = mountaineer_rs.render_ssr(
            full_script, int(hard_timeout * 1000) if hard_timeout else 0
        )
    except ConnectionAbortedError:
        raise TimeoutError("SSR render was interrupted after hard timeout")
    except ValueError as e:
        js_stack = fix_exception_lines(
            exception=str(e), injected_script=injected_script
        )

        if sourcemap:
            sourcemap_parser = SourceMapParser(script=sourcemap)
            sourcemap_parser.parse()
            js_stack = sourcemap_parser.map_exception(js_stack)

        raise V8RuntimeError(js_stack)

    return cast(str, render_result)
