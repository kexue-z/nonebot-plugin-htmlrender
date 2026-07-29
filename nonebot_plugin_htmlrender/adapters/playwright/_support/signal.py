from collections.abc import Generator
from contextlib import contextmanager
import os
import signal
import sys
import threading
from types import FrameType
from typing import Callable

WINDOWS = sys.platform.startswith("win") or (sys.platform == "cli" and os.name == "nt")

HANDLED_SIGNALS = (
    signal.SIGINT,
    signal.SIGTERM,
)
if WINDOWS:
    HANDLED_SIGNALS += (signal.SIGBREAK,)


_handlers: list[Callable[[int, FrameType | None], None]] = []
_original_signal_handlers: dict[
    int, int | Callable[[int, FrameType | None], None] | None
] = {}


class _SignalInstallState:
    """记录信号分发器的安装状态。"""

    def __init__(self) -> None:
        self.installed = False


_install_state = _SignalInstallState()


class _ShieldContext:
    """信号屏蔽计数器。

    通过引用计数支持 ``shield_signals`` 嵌套使用：计数大于 0 时屏蔽信号。
    """

    def __init__(self) -> None:
        self._counter = 0

    def acquire(self) -> None:
        """进入屏蔽区，递增计数。"""
        self._counter += 1

    def release(self) -> None:
        """离开屏蔽区，递减计数。"""
        self._counter -= 1

    def active(self) -> bool:
        """判断当前是否处于屏蔽状态。

        Returns:
            屏蔽计数大于 0 时返回 ``True``。
        """
        return self._counter > 0


_shield_context = _ShieldContext()


def _restore_signal_handlers() -> None:
    """恢复原始信号处理器。

    将所有已处理信号的处理器恢复为安装前的原始状态，
    并清除保存的原始处理器记录。
    """
    if not _install_state.installed:
        return

    for sig in HANDLED_SIGNALS:
        original = _original_signal_handlers.get(sig)
        if original is not None:
            signal.signal(sig, original)

    _original_signal_handlers.clear()
    _install_state.installed = False


def install_signal_handler() -> None:
    """安装自定义信号处理分发器。

    为所有需要处理的信号安装统一的分发函数，保存原始处理器以便恢复。
    仅在主线程中生效，且只安装一次。
    """
    if threading.current_thread() is not threading.main_thread():
        return
    if _install_state.installed:
        return

    for sig in HANDLED_SIGNALS:
        _original_signal_handlers[sig] = signal.getsignal(sig)
        signal.signal(sig, _handle_signal)

    _install_state.installed = True


def _handle_signal(signum: int, frame: FrameType | None) -> None:
    """信号分发处理函数。

    收到信号时依次调用所有已注册的处理回调。若信号被屏蔽则忽略，
    若无已注册的处理器则恢复原始处理器并重新触发信号。

    Args:
        signum: 接收到的信号编号。
        frame: 被中断的栈帧。
    """
    if _shield_context.active():
        return

    handlers = tuple(_handlers)
    for handler in handlers:
        handler(signum, frame)

    if not handlers:
        _restore_signal_handlers()
        signal.raise_signal(signum)


def register_signal_handler(handler: Callable[[int, FrameType | None], None]) -> None:
    """注册信号处理回调。

    将处理器添加到回调列表中，并确保信号分发器已安装。

    Args:
        handler: 信号处理回调函数，接收信号编号和栈帧。
    """
    _handlers.append(handler)
    install_signal_handler()


def remove_signal_handler(handler: Callable[[int, FrameType | None], None]) -> None:
    """移除信号处理回调。

    从回调列表中移除指定的处理器。若移除后列表为空，则恢复原始信号处理器。

    Args:
        handler: 要移除的信号处理回调函数。
    """
    _handlers.remove(handler)
    if not _handlers:
        _restore_signal_handlers()


@contextmanager
def shield_signals() -> Generator[None, None, None]:
    """临时屏蔽信号处理的上下文管理器。

    在上下文内收到的信号将被忽略，支持嵌套使用。
    """
    _shield_context.acquire()
    try:
        yield
    finally:
        _shield_context.release()


__all__ = [
    "HANDLED_SIGNALS",
    "WINDOWS",
    "install_signal_handler",
    "register_signal_handler",
    "remove_signal_handler",
    "shield_signals",
]
