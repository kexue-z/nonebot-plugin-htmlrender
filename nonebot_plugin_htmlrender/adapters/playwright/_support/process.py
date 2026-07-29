from __future__ import annotations

from contextlib import asynccontextmanager, nullcontext
import inspect
import os
import signal
import subprocess
from typing import TYPE_CHECKING, final

import anyio
from exceptiongroup import BaseExceptionGroup

from .signal import (
    WINDOWS,
    register_signal_handler,
    remove_signal_handler,
    shield_signals,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping
    from pathlib import Path
    from types import FrameType
    from typing import IO

    from anyio.abc import Process, TaskGroup

INTERRUPT_SIGNAL_ATTR = "_htmlrender_received_signal"


@final
class ProcessSupervisor:
    """Own subprocess watchers for one explicit structured-concurrency scope."""

    def __init__(self, task_group: TaskGroup) -> None:
        self._task_group = task_group
        self._processes: dict[int, Process] = {}
        self._closed = False

    async def manage(self, process: Process) -> Process:
        """Register signal and completion watchers for one spawned process."""
        if self._closed:
            await terminate_process(process)
            raise RuntimeError("Process supervisor is already closed.")

        should_exit = anyio.Event()
        handler_removed = False

        def shutdown(signum: int, _frame: FrameType | None) -> None:
            setattr(process, INTERRUPT_SIGNAL_ATTR, signum)
            should_exit.set()

        def remove_shutdown_handler() -> None:
            nonlocal handler_removed
            if handler_removed:
                return
            handler_removed = True
            remove_signal_handler(shutdown)

        async def wait_for_exit() -> None:
            try:
                await should_exit.wait()
                await terminate_process(process)
            finally:
                remove_shutdown_handler()
                self._processes.pop(id(process), None)

        async def wait_for_finish() -> None:
            try:
                await process.wait()
                should_exit.set()
            finally:
                remove_shutdown_handler()
                self._processes.pop(id(process), None)

        setattr(process, INTERRUPT_SIGNAL_ATTR, None)
        self._processes[id(process)] = process
        register_signal_handler(shutdown)
        try:
            self._task_group.start_soon(wait_for_exit)
            self._task_group.start_soon(wait_for_finish)
        except BaseException:
            self._processes.pop(id(process), None)
            remove_shutdown_handler()
            await terminate_process(process)
            raise
        return process

    async def aclose(self) -> None:
        """Terminate every process still owned by this supervisor."""
        if self._closed:
            return
        self._closed = True
        errors: list[BaseException] = []
        for process in tuple(self._processes.values()):
            try:
                await terminate_process(process)
            except BaseException as error:  # noqa: PERF203 -- best-effort teardown
                errors.append(error)
        if errors:
            raise BaseExceptionGroup("Failed to close supervised subprocesses.", errors)


@asynccontextmanager
async def open_process_supervisor() -> AsyncIterator[ProcessSupervisor]:
    """Create an explicitly owned subprocess watcher scope."""
    async with anyio.create_task_group() as task_group:
        supervisor = ProcessSupervisor(task_group)
        try:
            yield supervisor
        finally:
            try:
                with anyio.CancelScope(shield=True):
                    await supervisor.aclose()
            finally:
                task_group.cancel_scope.cancel()


async def create_process(
    *args: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    supervisor: ProcessSupervisor,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    stdin: IO[bytes] | int | None = None,
    stdout: IO[bytes] | int | None = None,
    stderr: IO[bytes] | int | None = None,
    start_new_session: bool | None = None,
) -> Process:
    """Spawn a subprocess with signal-driven termination protection.

    Uses CREATE_NEW_PROCESS_GROUP on Windows and a new session on Unix. When
    ``env`` is provided it becomes the child's complete environment; the
    parent process environment is never mutated.
    """
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0
    session = (
        False if WINDOWS else (True if start_new_session is None else start_new_session)
    )
    process = await anyio.open_process(
        args,
        cwd=cwd,
        env=None if env is None else dict(env),
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        creationflags=creation_flags,
        start_new_session=session,
    )
    return await supervisor.manage(process)


async def create_process_shell(
    command: str | bytes,
    *,
    supervisor: ProcessSupervisor,
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

    process = await anyio.open_process(
        shell_command,
        cwd=cwd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        creationflags=creation_flags,
    )
    return await supervisor.manage(process)


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
    "ProcessSupervisor",
    "create_process",
    "create_process_shell",
    "open_process_supervisor",
    "terminate_process",
]
