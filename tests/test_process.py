import asyncio
import os
from pathlib import Path

import pytest
from pytest_mock import MockerFixture


@pytest.fixture
def windows_env(mocker: MockerFixture):
    mocker.patch("nonebot_plugin_htmlrender.process.WINDOWS", True)


@pytest.fixture
def unix_env(mocker: MockerFixture):
    mocker.patch("nonebot_plugin_htmlrender.process.WINDOWS", False)


@pytest.fixture
async def long_running_process():
    # Use appropriate command based on platform
    command = "timeout /t 15" if os.name == "nt" else "sleep 15"
    proc = await asyncio.create_subprocess_shell(
        command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    yield proc
    if proc.returncode is None:
        proc.terminate()
        await proc.wait()


@pytest.mark.asyncio
async def test_create_process_basic():
    from nonebot_plugin_htmlrender.process import create_process

    if os.name == "nt":
        proc = await create_process("cmd", "/c", "echo", "test")
    else:
        proc = await create_process("echo", "test")
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.asyncio
async def test_create_process_with_cwd():
    from nonebot_plugin_htmlrender.process import create_process

    cwd = Path.cwd()
    if os.name == "nt":
        proc = await create_process("cmd", "/c", "cd", cwd=cwd)
    else:
        proc = await create_process("pwd", cwd=cwd)
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.asyncio
async def test_create_process_with_pipe():
    from nonebot_plugin_htmlrender.process import create_process

    if os.name == "nt":
        proc = await create_process(
            "cmd", "/c", "echo", "test", stdout=asyncio.subprocess.PIPE
        )
    else:
        proc = await create_process("echo", "test", stdout=asyncio.subprocess.PIPE)
    stdout, _ = await proc.communicate()
    assert b"test" in stdout.lower()


@pytest.mark.asyncio
async def test_create_process_shell_basic():
    from nonebot_plugin_htmlrender.process import create_process_shell

    command = "echo test"
    proc = await create_process_shell(command)
    assert isinstance(proc, asyncio.subprocess.Process)
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.asyncio
async def test_create_process_shell_with_cwd():
    from nonebot_plugin_htmlrender.process import create_process_shell

    cwd = Path.cwd()
    command = "cd" if os.name == "nt" else "pwd"
    proc = await create_process_shell(command, cwd=cwd)
    await proc.wait()
    assert proc.returncode == 0


@pytest.mark.asyncio
async def test_terminate_process(long_running_process):
    from nonebot_plugin_htmlrender.process import terminate_process

    await terminate_process(long_running_process)
    await long_running_process.wait()
    assert long_running_process.returncode != 0


@pytest.mark.asyncio
async def test_terminate_completed_process():
    from nonebot_plugin_htmlrender.process import create_process, terminate_process

    if os.name == "nt":
        proc = await create_process("cmd", "/c", "echo", "test")
    else:
        proc = await create_process("echo", "test")
    await proc.wait()
    original_returncode = proc.returncode
    await terminate_process(proc)
    assert proc.returncode == original_returncode


@pytest.mark.asyncio
async def test_terminate_process_windows(windows_env, long_running_process):
    from nonebot_plugin_htmlrender.process import terminate_process

    await terminate_process(long_running_process)
    await long_running_process.wait()
    assert long_running_process.returncode != 0


@pytest.mark.asyncio
async def test_terminate_process_unix(unix_env, long_running_process):
    from nonebot_plugin_htmlrender.process import terminate_process

    await terminate_process(long_running_process)
    await long_running_process.wait()
    assert long_running_process.returncode != 0


@pytest.mark.asyncio
async def test_ensure_process_terminated_decorator():
    from nonebot_plugin_htmlrender.process import (
        create_process,
        ensure_process_terminated,
    )

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
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await proc.wait()
        except asyncio.CancelledError:
            await terminate_process(proc)
            raise
        return proc

    async def terminate_process(_):
        if _ and _.returncode is None:
            _.terminate()
            await asyncio.shield(_.wait())

    task = asyncio.create_task(func())
    await asyncio.sleep(1.0)

    assert proc is not None, "Process was not created."
    assert isinstance(
        proc, asyncio.subprocess.Process
    ), "Process is not of expected type."
    assert proc.returncode is None, "Process already terminated prematurely."

    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        await terminate_process(proc)

    await asyncio.sleep(0.5)
    assert proc.returncode is not None, "Process did not terminate as expected."
