"""Retry utility decorator for resilient API calls."""

import asyncio
import inspect
import logging
import random
import time
from functools import wraps

logger = logging.getLogger(__name__)


def retry(max_attempts=3, delay=2, backoff=2, exceptions=(Exception,)):
    """API calls retry decorator — sync & async aware with jitter."""

    def decorator(func):
        is_async = inspect.iscoroutinefunction(func)

        if is_async:

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                last_exception: Exception = RuntimeError("Unknown error")
                for attempt in range(1, max_attempts + 1):
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if attempt < max_attempts:
                            wait = delay * (backoff ** (attempt - 1))
                            # M6 fix: Add jitter to prevent thundering herd
                            jitter = random.uniform(0, wait * 0.5)
                            total_wait = wait + jitter
                            logger.warning(
                                "%s attempt %d/%d failed: %s. Retrying in %.1fs...",
                                func.__name__,
                                attempt,
                                max_attempts,
                                e,
                                total_wait,
                            )
                            await asyncio.sleep(total_wait)
                        else:
                            logger.error(
                                "%s FAILED after %d attempts: %s",
                                func.__name__,
                                max_attempts,
                                e,
                            )
                raise last_exception

            return async_wrapper

        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                last_exception: Exception = RuntimeError("Unknown error")
                for attempt in range(1, max_attempts + 1):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if attempt < max_attempts:
                            wait = delay * (backoff ** (attempt - 1))
                            # M6 fix: Add jitter to prevent thundering herd
                            jitter = random.uniform(0, wait * 0.5)
                            total_wait = wait + jitter
                            logger.warning(
                                "%s attempt %d/%d failed: %s. Retrying in %.1fs...",
                                func.__name__,
                                attempt,
                                max_attempts,
                                e,
                                total_wait,
                            )
                            time.sleep(total_wait)
                        else:
                            logger.error(
                                "%s FAILED after %d attempts: %s",
                                func.__name__,
                                max_attempts,
                                e,
                            )
                raise last_exception

            return sync_wrapper

    return decorator
