from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from nonebot.log import logger

from ._support.install import MirrorSource
from ._support.install import (
    check_mirror_connectivity as _check_mirror_connectivity,
)
from ._support.install import (
    execute_install_command as _execute_install_command,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .config import PlaywrightConfig

_DOWNLOAD_HOST_VAR = "PLAYWRIGHT_DOWNLOAD_HOST"
_CONNECTION_TIMEOUT_VAR = "PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT"

MIRRORS: tuple[MirrorSource, ...] = (
    MirrorSource(
        "Taobao",
        "https://registry.npmmirror.com/-/binary/playwright",
        1,
    ),
)


def _redact_url(value: str) -> str:
    """Drop userinfo, query and fragment from a URL for logging."""
    try:
        parsed = urlsplit(value)
    except Exception:
        return value

    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _install_env(
    config: PlaywrightConfig,
    mirror: MirrorSource | None,
) -> dict[str, str]:
    """Build the subprocess environment for one install attempt.

    A copy of the caller environment plus the download timeout, the selected
    mirror host (only when ``mirror`` is given) and proxy variables. Existing
    parent proxy variables keep their priority and are never overwritten; the
    parent environment itself is not mutated.
    """
    env = dict(os.environ)
    env[_CONNECTION_TIMEOUT_VAR] = "300000"

    proxy = config.install_proxy
    if proxy:
        if proxy.startswith("http://") and not env.get("HTTP_PROXY"):
            logger.info(f"Using http Proxy: {_redact_url(proxy)}")
            env["HTTP_PROXY"] = proxy
        elif proxy.startswith("https://") and not env.get("HTTPS_PROXY"):
            logger.info(f"Using https Proxy: {_redact_url(proxy)}")
            env["HTTPS_PROXY"] = proxy

    if mirror is not None:
        env[_DOWNLOAD_HOST_VAR] = mirror.url
    else:
        env.pop(_DOWNLOAD_HOST_VAR, None)
    return env


async def check_mirror_connectivity(
    config: PlaywrightConfig,
    timeout_seconds: int = 5,
) -> MirrorSource | None:
    """检查镜像源连通性并返回最优镜像。

    Args:
        timeout_seconds: 连通性检测超时时间（秒）。

    Returns:
        可用的最优镜像源，若均不可用则返回 None。
    """
    mirrors = list(MIRRORS)
    if config.install_mirror:
        mirrors.append(MirrorSource("Custom mirror", config.install_mirror, 0))
    return await _check_mirror_connectivity(mirrors, timeout_seconds=timeout_seconds)


async def execute_install_command(
    config: PlaywrightConfig,
    timeout_seconds: int,
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    """Run ``playwright install`` for the configured engine.

    ``env`` is the subprocess's complete environment; the parent process
    environment is never mutated.
    """
    return await _execute_install_command(
        (
            sys.executable,
            "-m",
            "playwright",
            "install",
            "--with-deps",
            config.engine,
        ),
        timeout_seconds=timeout_seconds,
        env=env,
    )


def _is_install_interrupted(message: str) -> bool:
    """Return whether an install message denotes a signal interruption."""
    return message.startswith("Interrupted by signal")


async def install_browser(
    config: PlaywrightConfig,
    timeout_seconds: int = 300,
) -> bool:
    """Install the Playwright browser with mirror selection and one retry.

    The install subprocess receives an explicit environment carrying the
    selected mirror and proxy; the parent process environment is untouched.
    On mirror failure it retries once against the official source.

    Raises:
        KeyboardInterrupt: when the install is interrupted by a signal.
    """
    best_mirror = await check_mirror_connectivity(config)
    if best_mirror is not None:
        logger.opt(colors=True).info(
            f"Using mirror source: <cyan>{best_mirror.name}</cyan> "
            f"{_redact_url(best_mirror.url)}"
        )
    else:
        logger.info("No mirror source is available; using default source.")

    logger.opt(colors=True).info(
        f"Checking <cyan>{config.engine}</cyan> installation..."
    )
    installed, message = await execute_install_command(
        config,
        timeout_seconds,
        env=_install_env(config, best_mirror),
    )
    if installed:
        logger.info("Installation succeeded")
        return True
    if _is_install_interrupted(message):
        logger.warning(message)
        raise KeyboardInterrupt(message)

    logger.warning("Installation failed, retrying with official mirror...")
    installed, message = await execute_install_command(
        config,
        timeout_seconds,
        env=_install_env(config, None),
    )
    if installed:
        logger.info("Installation succeeded")
        return True
    if _is_install_interrupted(message):
        logger.warning(message)
        raise KeyboardInterrupt(message)

    logger.error(f"Installation failed with: {message}")
    return False


__all__ = [
    "MirrorSource",
    "check_mirror_connectivity",
    "execute_install_command",
    "install_browser",
]
