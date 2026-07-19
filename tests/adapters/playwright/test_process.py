from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

import anyio
from anyio import EndOfStream
import pytest

from nonebot_plugin_htmlrender.adapters.playwright._support.process import (
    ProcessSupervisor,
    create_process,
    create_process_shell,
    open_process_supervisor,
    terminate_process,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def process_supervisor() -> AsyncIterator[ProcessSupervisor]:
    async with open_process_supervisor() as supervisor:
        yield supervisor


@pytest.fixture
async def long_running_process():
    command = ["cmd", "/c", "timeout /t 15"] if os.name == "nt" else ["sleep", "15"]
    proc = await anyio.open_process(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=(os.name != "nt"),
    )
    try:
        yield proc
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


@pytest.mark.anyio
async def test_create_process_basic(process_supervisor: ProcessSupervisor):
    if os.name == "nt":
        proc = await create_process(
            "cmd", "/c", "echo", "test", supervisor=process_supervisor
        )
    else:
        proc = await create_process("echo", "test", supervisor=process_supervisor)
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.anyio
async def test_create_process_with_cwd(process_supervisor: ProcessSupervisor):
    cwd = Path.cwd()
    if os.name == "nt":
        proc = await create_process(
            "cmd", "/c", "cd", supervisor=process_supervisor, cwd=cwd
        )
    else:
        proc = await create_process("pwd", supervisor=process_supervisor, cwd=cwd)
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.anyio
async def test_create_process_with_pipe(process_supervisor: ProcessSupervisor):
    if os.name == "nt":
        proc = await create_process(
            "cmd",
            "/c",
            "echo",
            "test",
            supervisor=process_supervisor,
            stdout=subprocess.PIPE,
        )
    else:
        proc = await create_process(
            "echo", "test", supervisor=process_supervisor, stdout=subprocess.PIPE
        )

    assert proc.stdout is not None
    data = b""
    while True:
        try:
            data += await proc.stdout.receive(65536)
        except EndOfStream:  # noqa: PERF203
            break

    assert b"test" in data.lower()


@pytest.mark.anyio
async def test_create_process_shell_basic(process_supervisor: ProcessSupervisor):
    command = "echo test"
    proc = await create_process_shell(command, supervisor=process_supervisor)
    assert proc.pid > 0
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.anyio
async def test_create_process_shell_with_cwd(process_supervisor: ProcessSupervisor):
    cwd = Path.cwd()
    command = "cd" if os.name == "nt" else "pwd"
    proc = await create_process_shell(command, supervisor=process_supervisor, cwd=cwd)
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.anyio
async def test_terminate_process(long_running_process):
    await terminate_process(long_running_process)
    await long_running_process.wait()
    assert long_running_process.returncode != 0


@pytest.mark.anyio
async def test_terminate_completed_process(process_supervisor: ProcessSupervisor):
    if os.name == "nt":
        proc = await create_process(
            "cmd", "/c", "echo", "test", supervisor=process_supervisor
        )
    else:
        proc = await create_process("echo", "test", supervisor=process_supervisor)
    await proc.wait()
    original_returncode = proc.returncode
    await terminate_process(proc)
    assert proc.returncode == original_returncode


@pytest.mark.anyio
async def test_terminate_process_unix(long_running_process):
    await terminate_process(long_running_process)
    await long_running_process.wait()
    assert long_running_process.returncode != 0


@pytest.mark.anyio
async def test_process_supervisor_terminates_live_process_on_exit():
    proc = None
    async with open_process_supervisor() as supervisor:
        command = (
            ["cmd", "/c", "ping -n 20 -w 1000 127.0.0.1"]
            if os.name == "nt"
            else ["sleep", "10"]
        )
        proc = await create_process(
            *command,
            supervisor=supervisor,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert proc.pid > 0
        assert proc.returncode is None

    assert proc.returncode is not None, "Process did not terminate as expected."


def test_process_supervisor_is_not_bound_to_previous_backend():
    async def open_and_close() -> None:
        async with open_process_supervisor():
            pass

    anyio.run(open_and_close, backend="asyncio")
    anyio.run(open_and_close, backend="trio")
