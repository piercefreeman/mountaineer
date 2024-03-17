import functools
from collections import OrderedDict
from hashlib import sha256
from json import dumps as json_dumps
from typing import Any, Callable

from pydantic import BaseModel

from mountaineer.logging import LOGGER


class LRUCache:
    def __init__(self, capacity: int, max_size_bytes: int | None):
        self.cache: OrderedDict[str, Any] = OrderedDict()
        self.capacity = capacity
        self.max_size_bytes = max_size_bytes

    def get(self, key: str):
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key: str, value: Any, size_bytes: int):
        if self.max_size_bytes and size_bytes > self.max_size_bytes:
            LOGGER.warning(
                f"Skipping cache for {key} as item exceeds the max size limit."
            )
            return
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

    def clear(self):
        self.cache.clear()


def serialize_args(args, kwargs):
    """
    Serialize function arguments to a JSON-compatible format.
    """
    serialized: list[Any | tuple[str, Any]] = []
    for arg in args:
        if isinstance(arg, BaseModel):
            serialized.append(arg.model_dump_json())
        else:
            serialized.append(arg)
    for key, value in kwargs.items():
        if isinstance(value, BaseModel):
            serialized.append((key, value.model_dump_json()))
        else:
            serialized.append((key, value))
    return json_dumps(serialized, sort_keys=True)


def extended_lru_cache(maxsize: int, max_size_mb: float | None = None):
    """
    Main entrypoint to our custom LRU cache. Unlike the standard python version,
    this has special handling for:
    - Pydantic BaseModels, converts values to json to ensure we can hash all of the values
    - A max_size_mb parameter to limit the size of each element of the cache. If a new
        request/response set of values exceeds this size, it will not be cached.

    Will inject a `use_cache` optional argument to the function signature too, so you can
    disable caching per request if needed.

    """
    max_size_bytes = int(max_size_mb * 1024 * 1024) if max_size_mb is not None else None

    def decorator(func: Callable):
        cache = LRUCache(capacity=maxsize, max_size_bytes=max_size_bytes)

        @functools.wraps(func)
        def wrapper(*args, use_cache=True, **kwargs):
            serialized = serialize_args(args, kwargs)
            hash_key = sha256(serialized.encode()).hexdigest()

            if use_cache:
                if (result := cache.get(hash_key)) is not None:
                    return result

            result = func(*args, **kwargs)

            # Serialize result to check size
            if use_cache:
                serialized_result = json_dumps(result)
                size_bytes = len(serialized_result.encode("utf-8"))
                cache.put(hash_key, result, size_bytes)

            return result

        setattr(wrapper, "_cache", cache)
        return wrapper

    return decorator
