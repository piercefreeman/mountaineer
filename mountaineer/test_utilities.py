"""
Utilities for unit and integration tests
"""
from functools import wraps
from inspect import isawaitable, iscoroutinefunction, signature
from tempfile import NamedTemporaryFile
from time import time

import pytest

from mountaineer.logging import LOGGER


class ExecutionTooLong(Exception):
    pass


def benchmark_function(max_time_seconds: int | float):
    """
    Wrap test functions in a timer that will enforce that the core logic completes
    in less than `max_time_seconds` seconds. Injects `start_timing` and `end_timing` into
    the function kwargs that will be called. Client callers should call these to scope
    where they want us to measure the core logic.

    """
    import pyinstrument

    def wrapper_fn(test_func):
        # We want to remove our custom functions from the signature, since pytest will natively
        # try to inject fixtures in this place
        orig_sig = signature(test_func)
        new_params = [
            p
            for name, p in orig_sig.parameters.items()
            if name not in {"start_timing", "end_timing"}
        ]
        new_sig = orig_sig.replace(parameters=new_params)

        # Make sure that our function is a coroutine (if it is we assume user has decorated it with
        # pytest.mark.asyncio), otherwise we should raise an error because pytest won't know how
        # to run it
        if not iscoroutinefunction(test_func):
            raise Exception(
                f"Test function {test_func.__name__} is not a coroutine function. Please decorate it with pytest.mark.asyncio"
            )

        @wraps(test_func)
        async def wrapper(*args, **kwargs):
            bound = new_sig.bind(*args, **kwargs)
            bound.apply_defaults()

            # Try to run the test function regularly, and time it
            # Instrumenting profilers at this point typically will slow down execution time
            start: float | None = None
            end: float | None = None

            def start_timing():
                nonlocal start
                start = time()

            def end_timing():
                nonlocal end
                end = time()

            try:
                result = test_func(
                    *args, **kwargs, start_timing=start_timing, end_timing=end_timing
                )
                if isawaitable(result):
                    result = await result

                if start is None:
                    raise Exception("Test function did not call start_timing")
                if end is None:
                    raise Exception("Test function did not call end_timing")

                LOGGER.info(f"Test function took: {end - start}")

                if end - start > max_time_seconds:
                    raise ExecutionTooLong()

                return result

            except ExecutionTooLong as e:
                LOGGER.error(f"Test function failed due to: {e}")

                # This should already be true, but we want to be explicit to help mypy
                assert start is not None
                assert end is not None

                profiler = pyinstrument.Profiler()
                output_filename: str | None = None

                def start_timing():
                    nonlocal profiler
                    profiler.start()

                def end_timing():
                    nonlocal profiler
                    nonlocal output_filename
                    profiler.stop()
                    with NamedTemporaryFile(delete=False, suffix=".html") as file:
                        file.write(profiler.output_html().encode())
                    LOGGER.warning(f"PyInstrument profile saved at: {file.name}")
                    output_filename = file.name

                result = test_func(
                    *args, **kwargs, start_timing=start_timing, end_timing=end_timing
                )
                if isawaitable(result):
                    await result

                pytest.fail(
                    f"Test function failed in {end-start}s and profiles generated; Pyinstrument: {output_filename}"
                )

        wrapper.__signature__ = new_sig  # type: ignore
        return wrapper

    return wrapper_fn
