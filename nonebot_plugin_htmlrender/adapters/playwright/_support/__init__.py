"""Private Playwright process and installation support."""

from collections.abc import Generator
from contextlib import contextmanager

from nonebot.log import logger


@contextmanager
def suppress_and_log() -> Generator[None, None, None]:
    """Suppress cleanup failures after recording them."""
    try:
        yield
    except Exception as error:
        logger.opt(exception=error).warning("Error occurred while closing playwright.")


__all__ = ["suppress_and_log"]
