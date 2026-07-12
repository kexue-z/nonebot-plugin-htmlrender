from collections.abc import Awaitable, Generator
from contextlib import contextmanager
from functools import wraps
from typing import Callable, TypeVar
from typing_extensions import ParamSpec

import anyio
from nonebot.log import logger

P = ParamSpec("P")
R = TypeVar("R")


@contextmanager
def suppress_and_log() -> Generator[None, None, None]:
    """抑制异常并记录警告日志的上下文管理器。"""
    try:
        yield
    except Exception as e:
        logger.opt(exception=e).warning("Error occurred while closing playwright.")


def with_lock(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """为异步函数添加互斥锁的装饰器。

    Args:
        func: 需要加锁保护的异步函数。

    Returns:
        包装后的异步函数，同一时刻只允许一个调用执行。
    """
    lock = anyio.Lock()

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        async with lock:
            return await func(*args, **kwargs)

    return wrapper


__all__ = [
    "suppress_and_log",
    "with_lock",
]
