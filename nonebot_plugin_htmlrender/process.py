import asyncio
from collections.abc import Coroutine
from contextlib import nullcontext
from functools import wraps
import os
from pathlib import Path
import signal
import subprocess
from typing import IO, Any, Callable, Optional, Union
from typing_extensions import ParamSpec

from nonebot_plugin_htmlrender.consts import WINDOWS
from nonebot_plugin_htmlrender.signal import (
    register_signal_handler,
    remove_signal_handler,
    shield_signals,
)

P = ParamSpec("P")


def ensure_process_terminated(
    func: Callable[P, Coroutine[Any, Any, asyncio.subprocess.Process]],
) -> Callable[P, Coroutine[Any, Any, asyncio.subprocess.Process]]:
    """
    确保在函数退出时进程被终止的装饰器。

    Args:
        func: 需要被包装的函数。

    Examples:
        >>> @ensure_process_terminated
        ... async def func():
        ...     return await create_process("ls")
    """
    tasks: set[asyncio.Task] = set()

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> asyncio.subprocess.Process:
        should_exit = asyncio.Event()

        def shutdown(signum, frame):
            should_exit.set()

        register_signal_handler(shutdown)

        async def wait_for_exit():
            await should_exit.wait()
            await terminate_process(proc)

        async def wait_for_finish():
            await proc.wait()
            should_exit.set()

        proc = await func(*args, **kwargs)

        exit_task = asyncio.create_task(wait_for_exit())
        tasks.add(exit_task)
        exit_task.add_done_callback(tasks.discard)

        wait_task = asyncio.create_task(wait_for_finish())
        tasks.add(wait_task)
        wait_task.add_done_callback(tasks.discard)
        wait_task.add_done_callback(lambda t: remove_signal_handler(shutdown))

        return proc

    return wrapper


@ensure_process_terminated
async def create_process(
    *args: Union[str, bytes, "os.PathLike[str]", "os.PathLike[bytes]"],
    cwd: Optional[Path] = None,
    stdin: Optional[Union[IO[Any], int]] = None,
    stdout: Optional[Union[IO[Any], int]] = None,
    stderr: Optional[Union[IO[Any], int]] = None,
) -> asyncio.subprocess.Process:
    """
    创建一个新进程。

    Args:
        *args: 进程的命令和参数。
        cwd: 工作目录。默认为 None。
        stdin: 标准输入。默认为 None。
        stdout: 标准输出。默认为 None。
        stderr: 标准错误。默认为 None。

    Returns:
        asyncio.subprocess.Process: 新进程。

    Examples:
        >>> async def func():
        ...     return await create_process("ls")

        >>> async def func():
        ...     return await create_process("ls", cwd="/")
    """
    return await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0,
    )


@ensure_process_terminated
async def create_process_shell(
    command: Union[str, bytes],
    cwd: Optional[Path] = None,
    stdin: Optional[Union[IO[Any], int]] = None,
    stdout: Optional[Union[IO[Any], int]] = None,
    stderr: Optional[Union[IO[Any], int]] = None,
) -> asyncio.subprocess.Process:
    """
    使用 shell 创建一个新进程。

    Args:
        command: 要运行的命令。
        cwd: 工作目录。默认为 None。
        stdin: 标准输入。默认为 None。
        stdout: 标准输出。默认为 None。
        stderr: 标准错误。默认为 None。

    Returns:
        asyncio.subprocess.Process: 新进程。

    Examples:
        >>> async def func():
        ...     return await create_process_shell("ls")

        >>> async def func():
        ...     return await create_process_shell("ls", cwd="/")
    """
    return await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0,
    )


async def terminate_process(process: asyncio.subprocess.Process) -> None:
    """
    终止一个进程。

    Args:
        process: 要终止的进程。
    """
    if process.returncode is not None:
        return

    context = shield_signals() if WINDOWS else nullcontext()

    with context:
        if WINDOWS:
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()

        await process.wait()
