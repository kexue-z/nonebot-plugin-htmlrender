from __future__ import annotations

from contextlib import asynccontextmanager
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
    from .config import PlaywrightConfig

MIRRORS: tuple[MirrorSource, ...] = (
    MirrorSource(
        "Taobao",
        "https://registry.npmmirror.com/-/binary/playwright",
        1,
    ),
)


def _redact_url(value: str) -> str:
    """脱敏 URL，移除查询参数和认证信息。"""
    try:
        parsed = urlsplit(value)
    except Exception:
        return value

    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


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


@asynccontextmanager
async def download_context(config: PlaywrightConfig):
    """配置下载环境的异步上下文管理器。

    在进入时设置镜像源和代理环境变量，退出时恢复原始环境。
    """
    had_original = "PLAYWRIGHT_DOWNLOAD_HOST" in os.environ
    original_host = os.environ.get("PLAYWRIGHT_DOWNLOAD_HOST")
    os.environ["PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT"] = "300000"

    if config.install_proxy:
        proxy = config.install_proxy
        if proxy.startswith("http://") and not os.environ.get("HTTP_PROXY"):
            logger.info(f"Using http Proxy: {_redact_url(proxy)}")
            os.environ["HTTP_PROXY"] = proxy
        elif proxy.startswith("https://") and not os.environ.get("HTTPS_PROXY"):
            logger.info(f"Using https Proxy: {_redact_url(proxy)}")
            os.environ["HTTPS_PROXY"] = proxy

    try:
        best_mirror = await check_mirror_connectivity(config)
        if best_mirror is not None:
            logger.opt(colors=True).info(
                f"Using mirror source: <cyan>{best_mirror.name}</cyan> {best_mirror.url}"
            )
            os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] = best_mirror.url
        else:
            logger.info("No mirror source is available; using default source.")

        yield
    finally:
        if had_original and original_host is not None:
            os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] = original_host
        elif "PLAYWRIGHT_DOWNLOAD_HOST" in os.environ:
            del os.environ["PLAYWRIGHT_DOWNLOAD_HOST"]

        if "HTTP_PROXY" in os.environ:
            del os.environ["HTTP_PROXY"]
        if "HTTPS_PROXY" in os.environ:
            del os.environ["HTTPS_PROXY"]


async def execute_install_command(
    config: PlaywrightConfig,
    timeout_seconds: int,
) -> tuple[bool, str]:
    """执行 Playwright 浏览器安装命令。

    Args:
        timeout_seconds: 命令执行超时时间（秒）。

    Returns:
        元组 (是否成功, 结果描述消息)。
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
    )


def _is_install_interrupted(message: str) -> bool:
    """检查安装消息是否表示因信号中断。"""
    return message.startswith("Interrupted by signal")


async def install_browser(
    config: PlaywrightConfig,
    timeout_seconds: int = 300,
) -> bool:
    """安装 Playwright 浏览器，带镜像源选择和重试逻辑。

    Args:
        timeout_seconds: 安装超时时间（秒）。

    Returns:
        安装成功返回 True，否则返回 False。

    Raises:
        KeyboardInterrupt: 安装被信号中断时。
    """
    async with download_context(config):
        logger.opt(colors=True).info(
            f"Checking <cyan>{config.engine}</cyan> installation..."
        )
        installed, message = await execute_install_command(config, timeout_seconds)
        if installed:
            logger.info("Installation succeeded")
            return True
        if _is_install_interrupted(message):
            logger.warning(message)
            raise KeyboardInterrupt(message)

        logger.warning("Installation failed, retrying with official mirror...")
        os.environ.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)
        installed, message = await execute_install_command(config, timeout_seconds)
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
    "download_context",
    "execute_install_command",
    "install_browser",
]
