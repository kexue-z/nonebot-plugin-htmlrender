import asyncio
from collections.abc import Generator
from contextlib import contextmanager
import signal
import threading
from types import FrameType
from typing import Callable, Optional

from nonebot_plugin_htmlrender.consts import WINDOWS

HANDLED_SIGNALS = (
    signal.SIGINT,  # Unix signal 2. Sent by Ctrl+C.
    signal.SIGTERM,  # Unix signal 15. Sent by `kill <pid>`.
)
if WINDOWS:
    HANDLED_SIGNALS += (signal.SIGBREAK,)  # Windows signal 21. Sent by Ctrl+Break.

handlers: list[Callable[[int, Optional[FrameType]], None]] = []


class _ShieldContext:
    """信号屏蔽上下文类，管理信号屏蔽计数。

    用于在信号处理中提供信号屏蔽功能，防止在特定代码块中处理信号。
    """

    def __init__(self) -> None:
        """初始化信号屏蔽上下文。

        设置信号屏蔽计数器为0。
        """
        self._counter = 0

    def acquire(self) -> None:
        """增加信号屏蔽计数器。

        调用此方法后，信号处理将被屏蔽，直到调用release()。
        """
        self._counter += 1

    def release(self) -> None:
        """减少信号屏蔽计数器。

        调用此方法后，信号屏蔽计数器减一，直到计数器归零，信号处理才会重新生效。
        """
        self._counter -= 1

    def active(self) -> bool:
        """检查是否处于信号屏蔽状态。

        返回：
            bool: 如果信号屏蔽计数器大于0，表示处于信号屏蔽状态。
        """
        return self._counter > 0


shield_context = _ShieldContext()


def install_signal_handler() -> None:
    """安装信号处理器。

    该方法会将适当的信号处理程序安装到事件循环中，确保信号在主线程中得到处理。

    仅允许在主线程中安装信号处理器。
    """
    if threading.current_thread() is not threading.main_thread():
        # Signals can only be listened to from the main thread.
        return

    loop = asyncio.get_event_loop()

    try:
        for sig in HANDLED_SIGNALS:
            loop.add_signal_handler(sig, handle_signal, sig, None)
    except NotImplementedError:
        # Windows
        for sig in HANDLED_SIGNALS:
            signal.signal(sig, handle_signal)


def handle_signal(signum: int, frame: Optional[FrameType]) -> None:
    """处理信号。

    该方法在收到信号时被调用。如果信号屏蔽处于活动状态，则忽略信号。

    Args:
        signum (int): 信号编号。
        frame (Optional[FrameType]): 当前的栈帧，通常可以为None。
    """
    if shield_context.active():
        return

    for handler in handlers:
        handler(signum, frame)


def register_signal_handler(
    handler: Callable[[int, Optional[FrameType]], None],
) -> None:
    """注册信号处理函数。

    将信号处理函数添加到处理列表中，以便当信号触发时调用。

    Args:
        handler (Callable[[int, Optional[FrameType]], None]): 处理信号的回调函数。
    """
    handlers.append(handler)


def remove_signal_handler(handler: Callable[[int, Optional[FrameType]], None]) -> None:
    """移除已注册的信号处理函数。

    从处理函数列表中删除指定的信号处理函数。

    Args:
        handler (Callable[[int, Optional[FrameType]], None]): 要移除的信号处理函数。
    """
    handlers.remove(handler)


@contextmanager
def shield_signals() -> Generator[None, None, None]:
    """信号屏蔽上下文管理器。

    在`with`语句中使用时，信号会被屏蔽，直到退出`with`语句时才恢复信号处理。

    使用此上下文管理器可以暂时禁用信号处理，避免在特定代码块中处理信号。

    Examples:
        >>> with shield_signals():
        ...     pass
    """
    shield_context.acquire()
    try:
        yield
    finally:
        shield_context.release()
