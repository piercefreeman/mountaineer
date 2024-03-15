import asyncio
from time import monotonic_ns

import pytest
from pydantic import BaseModel

from mountaineer.__tests__.common import calculate_primes
from mountaineer.cropper import FunctionCropException, crop_function_for_return_keys


class ExampleResponse(BaseModel):
    a: int
    b: int


def test_simple_sync_function():
    """
    Make sure that we successfully crop the AST to only compute
    logic necessary for our output
    """

    def example_function():
        x = 5
        y = 10
        a = x + y + calculate_primes(10000)
        b = x + calculate_primes(1000000)
        return {"a": a, "b": b}

    optimized_func = crop_function_for_return_keys(example_function, ["a"], locals())

    # Our raw function execution should be over 1s
    # Our optimized function should be less than 0.05s
    start = monotonic_ns()
    output_value = example_function()
    assert ((monotonic_ns() - start) / 1e9) > 1
    assert output_value == {"a": 1244, "b": 78503}

    start = monotonic_ns()
    output_value = optimized_func()
    assert ((monotonic_ns() - start) / 1e9) < 0.05
    assert output_value == {"a": 1244}


def test_conditional_sync_function():
    """
    Test our ability to parse if/else statements
    """

    def example_function(x: int):
        if x > 50:
            a = calculate_primes(10)
            b = calculate_primes(1000000)
        else:
            a = calculate_primes(0)
            b = calculate_primes(1000000)
        return {"a": a, "b": b}

    optimized_func = crop_function_for_return_keys(example_function, ["a"], locals())

    start = monotonic_ns()
    output_value = optimized_func(100)
    assert ((monotonic_ns() - start) / 1e9) < 0.05
    assert output_value == {"a": 4}

    start = monotonic_ns()
    output_value = optimized_func(0)
    assert ((monotonic_ns() - start) / 1e9) < 0.05
    assert output_value == {"a": 0}


def test_pydantic_model():
    def example_function():
        x = 5
        y = 10
        a = x + y + calculate_primes(10000)
        b = x + calculate_primes(1000000)
        return ExampleResponse(a=a, b=b)

    optimized_func = crop_function_for_return_keys(example_function, ["a"], locals())

    start = monotonic_ns()
    output_value = optimized_func()
    assert ((monotonic_ns() - start) / 1e9) < 0.05
    assert output_value == {"a": 1244}


@pytest.mark.asyncio
async def test_async_function():
    async def example_fn_short():
        await asyncio.sleep(0.001)
        return 5

    async def example_fn_long():
        await asyncio.sleep(10)
        return 10

    async def example_function_async():
        x = 5
        y = 10
        a = x + y + await example_fn_short()
        b = x + await example_fn_long()
        return ExampleResponse(a=a, b=b)

    optimized_func_async = crop_function_for_return_keys(
        example_function_async, ["a"], locals()
    )

    start = monotonic_ns()
    output_value = await optimized_func_async()
    assert ((monotonic_ns() - start) / 1e9) < 0.05
    assert output_value == {"a": 20}


def test_invalid_return_type():
    def example_function():
        return 5

    with pytest.raises(FunctionCropException):
        crop_function_for_return_keys(example_function, ["a"], locals())
