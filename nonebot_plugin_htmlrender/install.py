import asyncio
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
import os
from typing import Callable, Optional
from urllib.parse import urlparse

from nonebot import logger

from nonebot_plugin_htmlrender.config import plugin_config
from nonebot_plugin_htmlrender.consts import MIRRORS, MirrorSource
from nonebot_plugin_htmlrender.process import create_process, terminate_process
from nonebot_plugin_htmlrender.signal import install_signal_handler


async def check_mirror_connectivity(timeout: int = 5) -> Optional[MirrorSource]:
    """检查镜像源的可用性并返回最佳镜像源。

    Args:
        timeout (int): 连接超时时间。

    Returns:
        Optional[MirrorSource]: 可用的最佳镜像源，如果没有可用镜像则返回 None。
    """

    async def _check_single_mirror(mirror: MirrorSource) -> tuple[MirrorSource, float]:
        """检查单个镜像源的可用性。"""
        try:
            parsed_url = urlparse(mirror.url)
            host = parsed_url.hostname
            port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)

            start_time = asyncio.get_event_loop().time()

            _, _ = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout
            )

            elapsed = asyncio.get_event_loop().time() - start_time
            return mirror, round(elapsed, 2)

        except Exception as e:
            logger.debug(f"镜像源 {mirror.name} 连接失败: {e!s}")
        return mirror, float("inf")

    if plugin_config.htmlrender_download_host:
        mirrors = [
            *MIRRORS,
            MirrorSource("自定义镜像", plugin_config.htmlrender_download_host, 0),
        ]
    else:
        mirrors = MIRRORS
    tasks = [_check_single_mirror(mirror) for mirror in mirrors]
    results: list[tuple[MirrorSource, float]] = await asyncio.gather(*tasks)

    available_mirrors = [(m, t) for m, t in results if t != float("inf")]
    if not available_mirrors:
        return None

    logger.debug(f"available_mirrors: {available_mirrors}")
    return min(available_mirrors, key=lambda x: (x[1], -x[0].priority))[0]


@asynccontextmanager
async def download_context() -> AsyncIterator[None]:
    """为下载设置上下文管理器，动态配置下载源和代理设置。

    该上下文管理器会设置合适的下载源和代理，并确保在退出时恢复原有环境变量。

    Yields:
        None: 占位符。
    """
    had_original = "PLAYWRIGHT_DOWNLOAD_HOST" in os.environ
    original_host = os.environ.get("PLAYWRIGHT_DOWNLOAD_HOST")
    os.environ["PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT"] = "300000"

    if plugin_config.htmlrender_download_proxy:
        proxy = plugin_config.htmlrender_download_proxy
        if proxy.startswith("http://") and not os.environ.get("HTTP_PROXY"):
            logger.info(f"Using http Proxy: {proxy}")
            os.environ["HTTP_PROXY"] = proxy
        elif proxy.startswith("https://") and not os.environ.get("HTTPS_PROXY"):
            logger.info(f"Using https Proxy: {proxy}")
            os.environ["HTTPS_PROXY"] = proxy

    try:
        best_mirror = await check_mirror_connectivity()
        if best_mirror is not None:
            logger.info(f"Using Mirror source: {best_mirror.name} ({best_mirror.url})")
            os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] = best_mirror.url
        else:
            logger.info("Mirror source not available, using default")

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


async def read_stream(
    stream: Optional[asyncio.StreamReader],
    callback: Optional[Callable[[str], Awaitable[None]]] = None,
) -> str:
    """读取流数据并处理每一行。

    对于包含进度的行，会触发进度回调。

    Args:
        stream (Optional[asyncio.StreamReader]): 用于读取数据的 asyncio.StreamReader
            对象。
        callback (Optional[Callable[[str], Awaitable[None]]]): 可选的回调函数，接收每一
            行的内容并返回一个 awaitable。

    Returns:
        str: 读取的所有内容。
    """
    if stream is None:
        return ""

    last_progress = ""  # 上一次显示的进度
    output = []  # 存储读取到的文本内容

    while True:
        try:
            char = await stream.read(1)
            if not char:
                break

            if char == b"\r":
                continue

            line = char + await stream.readuntil(b"\n")
            text = line.decode().strip()

            if "|" in text and "%" in text:
                if text != last_progress:
                    if callback:
                        await callback(f"Progress: {text}")
                    last_progress = text
            else:
                if callback:
                    await callback(text)
                output.append(text)

        except asyncio.IncompleteReadError:
            break
        except Exception as e:
            logger.opt(exception=True).error(f"Error reading stream: {e!s}")
            break

    return "\n".join(output)


async def execute_install_command(timeout: int) -> tuple[bool, str]:
    """执行浏览器安装命令。

    Args:
        timeout (int): 安装过程中等待的最大秒数。

    Returns:
        tuple[bool, str]: 安装是否成功以及相关消息。
    """
    try:
        logger.debug("Starting playwright install process...")
        install_signal_handler()
        process = await create_process(
            "playwright",
            "install",
            "--with-deps",
            plugin_config.htmlrender_browser,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.debug("Process created successfully")

        async def stdout_callback(line: str) -> None:
            logger.info(f"{line.strip()}")

        async def stderr_callback(line: str) -> None:
            logger.warning(f"Install error: {line.strip()}")

        stdout_task = asyncio.create_task(read_stream(process.stdout, stdout_callback))
        stderr_task = asyncio.create_task(read_stream(process.stderr, stderr_callback))

        try:
            await asyncio.wait_for(
                asyncio.gather(stdout_task, stderr_task), timeout=timeout
            )
        except asyncio.TimeoutError:
            await terminate_process(process)
            return False, f"Timed out ({timeout}s)"

        await process.wait()
        returncode = process.returncode

        if returncode != 0:
            return False, f"Exited with code {returncode}"

        return True, "Installation completed"

    except Exception as e:
        return False, f"An error occurred during installation: {e!s}"


async def install_browser(timeout: int = 300) -> bool:
    """安装用于 Playwright 的浏览器。

    Args:
        timeout (int): 安装过程中等待的最大秒数。

    Returns:
        bool: 是否安装成功。
    """
    async with download_context():
        logger.opt(colors=True).info(
            f"Checking <cyan>{plugin_config.htmlrender_browser}</cyan> installation..."
        )
        installed, message = await execute_install_command(timeout)
        if installed:
            logger.info("Installation succeeded")
            return True
        else:
            logger.warning("Installation failed, retrying with official mirror...")
            del os.environ["PLAYWRIGHT_DOWNLOAD_HOST"]
            installed, message = await execute_install_command(timeout)
            if installed:
                logger.info("Installation succeeded")
                return True
            else:
                logger.error(f"Installation failed with: {message}")
                return False
