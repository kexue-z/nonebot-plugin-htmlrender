import os
from pathlib import Path
import subprocess

import anyio
from anyio import EndOfStream
import pytest

from nonebot_plugin_htmlrender.adapters.playwright._support.process import (
    create_process,
    create_process_shell,
    ensure_process_terminated,
    terminate_process,
)


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
async def test_create_process_basic():
    if os.name == "nt":
        proc = await create_process("cmd", "/c", "echo", "test")
    else:
        proc = await create_process("echo", "test")
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.anyio
async def test_create_process_with_cwd():
    cwd = Path.cwd()
    if os.name == "nt":
        proc = await create_process("cmd", "/c", "cd", cwd=cwd)
    else:
        proc = await create_process("pwd", cwd=cwd)
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.anyio
async def test_create_process_with_pipe():
    if os.name == "nt":
        proc = await create_process("cmd", "/c", "echo", "test", stdout=subprocess.PIPE)
    else:
        proc = await create_process("echo", "test", stdout=subprocess.PIPE)

    assert proc.stdout is not None
    data = b""
    while True:
        try:
            data += await proc.stdout.receive(65536)
        except EndOfStream:  # noqa: PERF203
            break

    assert b"test" in data.lower()


@pytest.mark.anyio
async def test_create_process_shell_basic():
    command = "echo test"
    proc = await create_process_shell(command)
    assert proc.pid > 0
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.anyio
async def test_create_process_shell_with_cwd():
    cwd = Path.cwd()
    command = "cd" if os.name == "nt" else "pwd"
    proc = await create_process_shell(command, cwd=cwd)
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.anyio
async def test_terminate_process(long_running_process):
    await terminate_process(long_running_process)
    await long_running_process.wait()
    assert long_running_process.returncode != 0


@pytest.mark.anyio
async def test_terminate_completed_process():
    if os.name == "nt":
        proc = await create_process("cmd", "/c", "echo", "test")
    else:
        proc = await create_process("echo", "test")
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
async def test_ensure_process_terminated_decorator():
    proc = None

    @ensure_process_terminated
    async def func():
        nonlocal proc
        command = (
            ["cmd", "/c", "ping -n 20 -w 1000 127.0.0.1"]
            if os.name == "nt"
            else ["sleep", "10"]
        )
        proc = await create_process(
            *command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await proc.wait()
        return proc

    async with anyio.create_task_group() as tg:
        tg.start_soon(func)
        await anyio.sleep(1.0)

        assert proc is not None, "Process was not created."
        assert proc.pid > 0, "Process pid is invalid."
        assert proc.returncode is None, "Process already terminated prematurely."

        tg.cancel_scope.cancel()

    if proc is not None and proc.returncode is None:
        await terminate_process(proc)

    assert proc is not None
    assert proc.returncode is not None, "Process did not terminate as expected."
