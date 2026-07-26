from __future__ import annotations

import os
import subprocess

import anyio

from nonebot_plugin_htmlrender.adapters.playwright._support.process import (
    create_process,
    open_process_supervisor,
)


async def test_process_supervisor_terminates_owned_process_on_exit() -> None:
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

    assert proc.returncode is not None


def test_process_supervisor_is_not_bound_to_previous_backend() -> None:
    async def open_and_close() -> None:
        async with open_process_supervisor():
            pass

    anyio.run(open_and_close, backend="asyncio")
    anyio.run(open_and_close, backend="trio")
