from __future__ import annotations

from dataclasses import dataclass
import signal
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import anyio
from nonebot.log import logger

from .process import (
    INTERRUPT_SIGNAL_ATTR,
    create_process,
    open_process_supervisor,
    terminate_process,
)
from .signal import HANDLED_SIGNALS

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class MirrorSource:
    """One Playwright browser download mirror candidate."""

    name: str
    url: str
    priority: int


async def check_mirror_connectivity(
    mirrors: list[MirrorSource],
    *,
    timeout_seconds: int = 5,
) -> MirrorSource | None:
    """并发检测镜像源连通性并返回延迟最低的镜像。

    通过 TCP 连接测试每个镜像源的可达性，并发执行所有探测任务，
    从可用镜像中选择延迟最低的返回。

    Args:
        mirrors: 待检测的镜像源列表。
        timeout_seconds: 单个镜像探测的超时时间（秒）。

    Returns:
        延迟最低的可用镜像源，若全部不可用则返回 None。
    """

    async def _check_single_mirror(mirror: MirrorSource) -> tuple[MirrorSource, float]:
        try:
            parsed_url = urlparse(mirror.url)
            host = parsed_url.hostname
            port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
            if host is None:
                return mirror, float("inf")

            start_time = anyio.current_time()
            with anyio.fail_after(timeout_seconds):
                stream = await anyio.connect_tcp(host, port)
                await stream.aclose()
            elapsed = anyio.current_time() - start_time
            return mirror, round(elapsed, 2)
        except Exception as e:
            logger.debug(
                f"Mirror source {mirror.name} connectivity check failed: {e!s}"
            )
            return mirror, float("inf")

    results: list[tuple[MirrorSource, float]] = []
    result_lock = anyio.Lock()

    async def _probe(mirror: MirrorSource) -> None:
        result = await _check_single_mirror(mirror)
        async with result_lock:
            results.append(result)

    async with anyio.create_task_group() as task_group:
        for mirror in mirrors:
            task_group.start_soon(_probe, mirror)

    available = [(m, t) for m, t in results if t != float("inf")]
    if not available:
        return None

    logger.debug(f"Available mirrors with latency: {available}")
    return min(available, key=lambda x: (x[1], -x[0].priority))[0]


def _format_signal_name(signum: int) -> str:
    """将信号编号格式化为可读名称。

    Args:
        signum: 信号编号。

    Returns:
        信号名称字符串，无法识别时返回编号的字符串形式。
    """
    try:
        return signal.Signals(signum).name
    except ValueError:
        return str(signum)


def _interrupt_message_from_returncode(returncode: int) -> str | None:
    """从进程返回码推断中断信号消息。

    根据返回码判断进程是否因已处理的信号而中断，支持负返回码和
    128+信号编号两种约定。

    Args:
        returncode: 进程退出返回码。

    Returns:
        描述中断信号的消息字符串，若非信号中断则返回 None。
    """
    handled = set(HANDLED_SIGNALS)

    if -returncode in handled:
        return f"Interrupted by signal {_format_signal_name(-returncode)}"

    for handled_signal in handled:
        if returncode == 128 + handled_signal:
            return f"Interrupted by signal {_format_signal_name(handled_signal)}"

    return None


async def execute_install_command(
    command: tuple[str, ...],
    *,
    timeout_seconds: int,
    env: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    """Run one install command in a subprocess and report its result.

    Handles timeout, signal interruption and abnormal exit. ``env`` is the
    subprocess's complete environment; the parent environment is untouched.
    """
    try:
        logger.debug("Starting install process...")
        async with open_process_supervisor() as supervisor:
            process = await create_process(
                *command,
                supervisor=supervisor,
                env=env,
                start_new_session=False,
            )

            try:
                with anyio.fail_after(timeout_seconds):
                    await process.wait()
            except TimeoutError:
                logger.error(f"Timed out ({timeout_seconds}s)")
                await terminate_process(process)
                return False, f"Timed out ({timeout_seconds}s)"

            signal_received = getattr(process, INTERRUPT_SIGNAL_ATTR, None)
            if isinstance(signal_received, int) and signal_received in HANDLED_SIGNALS:
                return (
                    False,
                    f"Interrupted by signal {_format_signal_name(signal_received)}",
                )

            if process.returncode is None:
                return False, "Exited with unknown status"

            interrupted_message = _interrupt_message_from_returncode(process.returncode)
            if interrupted_message is not None:
                return False, interrupted_message

            if process.returncode != 0:
                return False, f"Exited with code {process.returncode}"

            return True, "Installation completed"
    except Exception as e:
        logger.error(f"An error occurred during installation: {e!s}")
        return False, f"An error occurred during installation: {e!s}"


__all__ = [
    "MirrorSource",
    "check_mirror_connectivity",
    "execute_install_command",
]
