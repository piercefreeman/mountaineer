from functools import wraps

from filzl.logging import LOGGER


def safe_task(fn):
    @wraps(fn)
    async def inner(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            LOGGER.error("Unhandled exception in task", exc_info=True)
            raise e

    return inner
