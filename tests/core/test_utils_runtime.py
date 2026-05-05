from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from nonebot_plugin_htmlrender import utils
from nonebot_plugin_htmlrender.consts import MirrorSource
from nonebot_plugin_htmlrender.utils import process as process_utils
from nonebot_plugin_htmlrender.utils import signal as signal_module
from nonebot_plugin_htmlrender.utils.install import (
    check_mirror_connectivity,
    execute_install_command,
)
from nonebot_plugin_htmlrender.utils.process import (
    create_process,
    create_process_shell,
    terminate_process,
)
from nonebot_plugin_htmlrender.utils.signal import (
    HANDLED_SIGNALS,
    _handle_signal,
    _handlers,
    install_signal_handler,
    register_signal_handler,
    remove_signal_handler,
    shield_signals,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _make_stream(*lines: bytes) -> asyncio.StreamReader:
    stream = asyncio.StreamReader()
    for line in lines:
        stream.feed_data(line)
    stream.feed_eof()
    return stream


@pytest.mark.anyio
async def test_with_lock_serializes_calls() -> None:
    started: list[int] = []
    finished: list[int] = []

    @utils.with_lock
    async def _job(index: int) -> int:
        started.append(index)
        await asyncio.sleep(0.01)
        finished.append(index)
        return index

    result = await asyncio.gather(*[_job(i) for i in range(3)])
    assert result == [0, 1, 2]
    assert started == [0, 1, 2]
    assert finished == [0, 1, 2]


def test_signal_handler_registration_and_shielding() -> None:
    calls: list[tuple[int, Any]] = []

    def _handler(signum: int, frame: Any) -> None:
        calls.append((signum, frame))

    _handlers.clear()
    register_signal_handler(_handler)
    _handle_signal(2, None)
    assert calls == [(2, None)]

    with shield_signals():
        _handle_signal(15, None)
    assert calls == [(2, None)]

    remove_signal_handler(_handler)
    assert _handlers == []


def test_install_signal_handler_non_main_thread_is_noop(
    mocker: MockerFixture,
) -> None:
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.signal.threading.current_thread",
        return_value=object(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.signal.threading.main_thread",
        return_value=object(),
    )
    signal_mock = mocker.patch("nonebot_plugin_htmlrender.utils.signal.signal.signal")

    install_signal_handler()
    signal_mock.assert_not_called()


def test_install_signal_handler_fallback_to_signal_api(
    mocker: MockerFixture,
) -> None:
    main = object()
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.signal.threading.current_thread",
        return_value=main,
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.signal.threading.main_thread",
        return_value=main,
    )
    signal_mock = mocker.patch("nonebot_plugin_htmlrender.utils.signal.signal.signal")

    install_signal_handler()

    assert signal_mock.call_count == len(HANDLED_SIGNALS)
    signal_module._restore_signal_handlers()


@pytest.mark.anyio
async def test_terminate_process_posix_with_lookup_fallback(
    mocker: MockerFixture,
) -> None:
    process = SimpleNamespace(
        returncode=None,
        pid=1234,
        wait=mocker.AsyncMock(),
        terminate=mocker.Mock(),
        kill=mocker.Mock(),
    )
    mocker.patch.object(process_utils, "WINDOWS", new=False)
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.process.os.getpgid",
        side_effect=ProcessLookupError,
    )
    killpg = mocker.patch("nonebot_plugin_htmlrender.utils.process.os.killpg")

    process_handle: Any = process
    await terminate_process(process_handle)

    process.terminate.assert_called_once_with()
    killpg.assert_not_called()
    process.wait.assert_awaited_once_with()


@pytest.mark.anyio
async def test_terminate_process_windows_timeout_kills_process(
    mocker: MockerFixture,
) -> None:
    process = SimpleNamespace(
        returncode=None,
        pid=777,
        wait=mocker.AsyncMock(),
        terminate=mocker.Mock(),
        kill=mocker.Mock(),
    )
    mocker.patch.object(process_utils, "WINDOWS", new=True)
    mocker.patch("nonebot_plugin_htmlrender.utils.process.os.kill")
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.process.signal.CTRL_BREAK_EVENT",
        new=21,
        create=True,
    )

    class _TimeoutNow:
        def __enter__(self) -> None:
            raise TimeoutError

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc_value: BaseException | None,
            _traceback: object,
        ) -> bool:
            return False

    mocker.patch(
        "nonebot_plugin_htmlrender.utils.process.anyio.fail_after",
        side_effect=lambda _seconds: _TimeoutNow(),
    )

    process_handle: Any = process
    await terminate_process(process_handle)

    process.kill.assert_called_once_with()
    assert process.wait.await_count == 1


@pytest.mark.anyio
async def test_check_mirror_connectivity_selects_best_and_handles_failures(
    mocker: MockerFixture,
) -> None:
    mirrors = [
        MirrorSource("A", "https://a.example.com", 1),
        MirrorSource("B", "https://b.example.com", 2),
        MirrorSource("C", "invalid", 3),
    ]
    timeline = iter([1.0, 1.3, 2.0, 2.1])
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.install.anyio.current_time",
        side_effect=lambda: next(timeline),
    )

    async def _connect_tcp(host: str, port: int):  # noqa: ARG001
        if host.startswith("b."):
            raise RuntimeError("down")
        return SimpleNamespace(aclose=mocker.AsyncMock())

    mocker.patch(
        "nonebot_plugin_htmlrender.utils.install.anyio.connect_tcp",
        side_effect=_connect_tcp,
    )

    best = await check_mirror_connectivity(mirrors)
    assert best is not None
    assert best.name == "A"


@pytest.mark.anyio
async def test_execute_install_command_result_paths(mocker: MockerFixture) -> None:
    process = SimpleNamespace(
        stdout=_make_stream(b"line\n"),
        stderr=_make_stream(),
        returncode=0,
        wait=mocker.AsyncMock(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.install.create_process",
        new=mocker.AsyncMock(return_value=process),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.install.terminate_process",
        new=mocker.AsyncMock(),
    )

    ok, message = await execute_install_command(("echo", "x"), timeout_seconds=1)
    assert ok is True
    assert "Installation completed" in message

    process2 = SimpleNamespace(
        stdout=_make_stream(),
        stderr=_make_stream(),
        returncode=5,
        wait=mocker.AsyncMock(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.install.create_process",
        new=mocker.AsyncMock(return_value=process2),
    )
    ok2, message2 = await execute_install_command(("echo", "x"), timeout_seconds=1)
    assert ok2 is False
    assert "Exited with code 5" in message2

    mocker.patch(
        "nonebot_plugin_htmlrender.utils.install.create_process",
        new=mocker.AsyncMock(side_effect=RuntimeError("boom")),
    )
    ok3, message3 = await execute_install_command(("echo", "x"), timeout_seconds=1)
    assert ok3 is False
    assert "An error occurred during installation" in message3


@pytest.mark.anyio
async def test_execute_install_command_timeout_path(mocker: MockerFixture) -> None:
    process = SimpleNamespace(
        stdout=_make_stream(),
        stderr=_make_stream(),
        returncode=0,
        wait=mocker.AsyncMock(),
    )
    mocker.patch(
        "nonebot_plugin_htmlrender.utils.install.create_process",
        new=mocker.AsyncMock(return_value=process),
    )
    terminate = mocker.patch(
        "nonebot_plugin_htmlrender.utils.install.terminate_process",
        new=mocker.AsyncMock(),
    )

    class _TimeoutNow:
        def __enter__(self) -> None:
            raise TimeoutError

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc_value: BaseException | None,
            _traceback: object,
        ) -> bool:
            return False

    mocker.patch(
        "nonebot_plugin_htmlrender.utils.install.anyio.fail_after",
        side_effect=lambda _seconds: _TimeoutNow(),
    )

    ok, message = await execute_install_command(("echo", "x"), timeout_seconds=1)
    assert ok is False
    assert message == "Timed out (1s)"
    terminate.assert_awaited_once_with(process)


@pytest.mark.anyio
async def test_create_process_and_shell_forward_to_anyio(mocker: MockerFixture) -> None:
    open_process = mocker.patch(
        "nonebot_plugin_htmlrender.utils.process.anyio.open_process",
        new=mocker.AsyncMock(return_value=object()),
    )
    mocker.patch.object(process_utils, "WINDOWS", new=False)

    proc_handle = SimpleNamespace(wait=mocker.AsyncMock(), returncode=0, pid=1)
    open_process.return_value = proc_handle

    proc = await create_process("python", "-V", cwd=Path.cwd())
    assert proc is not None
    open_process.assert_awaited()
    assert open_process.await_args_list[0].kwargs["start_new_session"] is True

    proc2 = await create_process_shell("echo 1")
    assert proc2 is not None
    assert open_process.await_count == 2
