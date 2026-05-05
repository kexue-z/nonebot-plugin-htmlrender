from collections.abc import Awaitable, Coroutine
from contextlib import nullcontext
from functools import wraps
import inspect
import os
from pathlib import Path
import signal
import subprocess
from types import FrameType
from typing import IO, Any, Callable, Union
from typing_extensions import ParamSpec

import anyio
from anyio.abc import Process, TaskGroup

from nonebot_plugin_htmlrender.consts import WINDOWS

from .signal import register_signal_handler, remove_signal_handler, shield_signals

P = ParamSpec("P")

INTERRUPT_SIGNAL_ATTR = "_htmlrender_received_signal"


class _BackgroundTaskGroupState:
    """保存进程级共享后台任务组的可变状态。"""

    def __init__(self) -> None:
        self.task_group: TaskGroup | None = None


_background_state = _BackgroundTaskGroupState()
_background_task_group_lock = anyio.Lock()


async def _ensure_background_task_group() -> TaskGroup:
    """确保后台任务组已初始化并返回。

    使用锁保证线程安全地创建单例任务组。若任务组尚未创建，
    则创建并进入其上下文。

    Returns:
        已初始化的后台任务组。
    """
    async with _background_task_group_lock:
        task_group = _background_state.task_group
        if task_group is None:
            task_group = anyio.create_task_group()
            await task_group.__aenter__()
            _background_state.task_group = task_group

    return task_group


async def _start_background_task(
    task_fn: Callable[..., Awaitable[None]],
    *task_args: Any,
) -> None:
    """在后台任务组中启动异步任务。

    Args:
        task_fn: 要执行的异步函数。
        task_args: 传递给异步函数的位置参数。
    """
    task_group = await _ensure_background_task_group()
    task_group.start_soon(task_fn, *task_args)


def ensure_process_terminated(
    process_factory: Callable[P, Coroutine[Any, Any, Process]],
) -> Callable[P, Coroutine[Any, Any, Process]]:
    """装饰器，确保子进程在信号中断时被正确终止。

    包装进程创建函数，注册信号处理器以在收到中断信号时自动终止
    由该工厂创建的子进程，并在进程正常结束后清理处理器。

    Args:
        process_factory: 创建子进程的异步工厂函数。

    Returns:
        包装后的工厂函数，创建的子进程具有信号中断保护。
    """

    @wraps(process_factory)
    async def wrapper(*call_args: P.args, **call_kwargs: P.kwargs) -> Process:
        should_exit = anyio.Event()
        managed_process: Process | None = None
        handler_removed = False

        def shutdown(signum: int, _frame: FrameType | None) -> None:
            if managed_process is not None:
                setattr(managed_process, INTERRUPT_SIGNAL_ATTR, signum)
            should_exit.set()

        def remove_shutdown_handler() -> None:
            nonlocal handler_removed
            if handler_removed:
                return
            handler_removed = True
            remove_signal_handler(shutdown)

        register_signal_handler(shutdown)

        async def wait_for_exit() -> None:
            try:
                await should_exit.wait()
                if managed_process is not None:
                    await terminate_process(managed_process)
            finally:
                remove_shutdown_handler()

        async def wait_for_finish() -> None:
            try:
                if managed_process is None:
                    return
                await managed_process.wait()
                should_exit.set()
            finally:
                remove_shutdown_handler()

        try:
            managed_process = await process_factory(*call_args, **call_kwargs)
            setattr(managed_process, INTERRUPT_SIGNAL_ATTR, None)
        except Exception:
            remove_shutdown_handler()
            raise

        await _start_background_task(wait_for_exit)
        await _start_background_task(wait_for_finish)
        return managed_process

    return wrapper


@ensure_process_terminated
async def create_process(
    *args: Union[str, bytes, "os.PathLike[str]", "os.PathLike[bytes]"],
    cwd: Path | None = None,
    stdin: IO[bytes] | int | None = None,
    stdout: IO[bytes] | int | None = None,
    stderr: IO[bytes] | int | None = None,
    start_new_session: bool | None = None,
) -> Process:
    """创建子进程并注册终止保护。

    在 Windows 上使用 CREATE_NEW_PROCESS_GROUP 标志，在 Unix 上默认
    创建新会话。进程创建后自动注册信号中断终止保护。

    Args:
        args: 要执行的命令及其参数。
        cwd: 子进程的工作目录。
        stdin: 标准输入流。
        stdout: 标准输出流。
        stderr: 标准错误流。
        start_new_session: 是否创建新会话（仅 Unix），默认为 True。

    Returns:
        创建的子进程对象。
    """
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0
    session = (
        False if WINDOWS else (True if start_new_session is None else start_new_session)
    )
    return await anyio.open_process(
        args,
        cwd=cwd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        creationflags=creation_flags,
        start_new_session=session,
    )


@ensure_process_terminated
async def create_process_shell(
    command: str | bytes,
    cwd: Path | None = None,
    stdin: IO[bytes] | int | None = None,
    stdout: IO[bytes] | int | None = None,
    stderr: IO[bytes] | int | None = None,
) -> Process:
    """通过 shell 创建子进程并注册终止保护。

    在 Windows 上使用 cmd /c 执行命令，在 Unix 上使用 $SHELL 或 /bin/sh。
    进程创建后自动注册信号中断终止保护。

    Args:
        command: 要执行的 shell 命令。
        cwd: 子进程的工作目录。
        stdin: 标准输入流。
        stdout: 标准输出流。
        stderr: 标准错误流。

    Returns:
        创建的子进程对象。
    """
    command_text = (
        command.decode(errors="replace") if isinstance(command, bytes) else command
    )

    if WINDOWS:
        shell_command: list[str] = ["cmd", "/c", command_text]
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        shell_command = [os.environ.get("SHELL", "/bin/sh"), "-c", command_text]
        creation_flags = 0

    return await anyio.open_process(
        shell_command,
        cwd=cwd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        creationflags=creation_flags,
    )


def _terminate_process_group(process_handle: object, sig: int) -> bool:
    """向进程组发送信号以终止。

    Args:
        process_handle: 进程对象，需要具有 pid 属性。
        sig: 要发送的信号编号。

    Returns:
        信号发送成功返回 True，失败返回 False。
    """
    pid = getattr(process_handle, "pid", None)
    if not isinstance(pid, int):
        return False
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


async def terminate_process(process_handle: object) -> None:
    """优雅终止进程，超时后强制 kill。

    先发送 SIGTERM（Windows 上为 CTRL_BREAK_EVENT），等待进程退出。
    若 5 秒内未退出，则发送 SIGKILL 强制终止。

    Args:
        process_handle: 要终止的进程对象。
    """
    returncode = getattr(process_handle, "returncode", None)
    if returncode is not None:
        return

    context = shield_signals() if WINDOWS else nullcontext()
    with context:
        pid = getattr(process_handle, "pid", None)
        if WINDOWS:
            if not isinstance(pid, int):
                return
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        elif not _terminate_process_group(process_handle, signal.SIGTERM):
            terminate = getattr(process_handle, "terminate", None)
            if callable(terminate):
                terminate()

        try:
            wait = getattr(process_handle, "wait", None)
            if not callable(wait):
                return
            with anyio.fail_after(5.0):
                first_wait = wait()
                if not inspect.isawaitable(first_wait):
                    return
                await first_wait
        except TimeoutError:
            if WINDOWS or not _terminate_process_group(process_handle, signal.SIGKILL):
                kill = getattr(process_handle, "kill", None)
                if callable(kill):
                    kill()
            wait = getattr(process_handle, "wait", None)
            if callable(wait):
                second_wait = wait()
                if inspect.isawaitable(second_wait):
                    await second_wait


__all__ = [
    "INTERRUPT_SIGNAL_ATTR",
    "create_process",
    "create_process_shell",
    "ensure_process_terminated",
    "terminate_process",
]
