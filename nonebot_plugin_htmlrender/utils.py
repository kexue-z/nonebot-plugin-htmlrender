from asyncio import Lock
from collections.abc import Awaitable
from contextlib import contextmanager
from functools import wraps
import os
from pathlib import Path
import platform
import re
import shutil
from typing import (
    Any,
    Callable,
    Optional,
    TypeVar,
    Union,
    overload,
)
from typing_extensions import ParamSpec
import warnings

from nonebot import logger
from nonebot.log import logger

from nonebot_plugin_htmlrender.config import plugin_config

P = ParamSpec("P")
R = TypeVar("R")
F = TypeVar("F", bound=Callable[..., Any])


@overload
def deprecated(func: Callable[P, R]) -> Callable[P, R]: ...


@overload
def deprecated(
    func: None = None,
    *,
    message: Optional[str] = None,
    version: Optional[str] = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def deprecated(
    func: Optional[Callable[P, R]] = None,
    *,
    message: Optional[str] = None,
    version: Optional[str] = None,
) -> Union[Callable[P, R], Callable[[Callable[P, R]], Callable[P, R]]]:
    """
    一个用于标记函数为已废弃的装饰器。

    可以通过两种方式使用:
    1. 作为简单装饰器:@deprecated
    2. 带参数的方式:@deprecated(message="...", version="...")

    Args:
        func: 需要标记为废弃的函数
        message: 自定义的废弃提示消息（可选）
        version: 标记为废弃的版本号（可选）

    Returns:
        如果没有传递参数，返回一个装饰器；
        否则返回已装饰的函数。

    Examples:
        >>> @deprecated
        ... def old_function():
        ...     pass

        >>> @deprecated(message="请使用 new_function() 代替", version="2.0.0")
        ... def another_old_function():
        ...     pass
    """

    def create_wrapper(f: Callable[P, R]) -> Callable[P, R]:
        @wraps(f)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # 生成废弃的警告信息
            warning_message = message or f"函数 '{f.__name__}' 已废弃。"
            if version:
                warning_message += f" (在版本 {version} 中被标记为废弃)"

            # 发出废弃警告
            warnings.warn(warning_message, category=DeprecationWarning, stacklevel=2)
            return f(*args, **kwargs)

        return wrapper

    return create_wrapper if func is None else create_wrapper(func)


@contextmanager
def suppress_and_log():
    """
    一个上下文管理器，用于抑制异常并记录任何发生的异常。

    该上下文管理器在特定操作（例如关闭资源）期间抑制异常，并在出现异常时将其记录下来。

    Examples:
        >>> with suppress_and_log():
        >>>     pass

    Yields:
        None: 没有返回值，但如果发生异常，会被捕获并记录。
    """
    try:
        yield
    except Exception as e:
        # 捕获异常并记录日志
        logger.opt(exception=e).warning("Error occurred while closing playwright.")


def proxy_settings(proxy_host: Optional[str]) -> Optional[dict]:
    """
    代理设置，解析提供的代理 URL，并检查是否包含用户名和密码，同时处理代理绕过。

    Args:
        proxy_host (Optional[str]): 代理主机的 URL。

    Returns:
        Optional[dict]: 代理设置。
    """
    if not proxy_host:
        return None

    proxy_pattern = re.compile(
        r"^(?P<protocol>https?|socks5?|http)://"
        r"(?P<username>[^:]+):(?P<password>[^@]+)"
        r"@(?P<host>[^:/]+)(?::(?P<port>\d+))?$",
        re.IGNORECASE,
    )

    if match := proxy_pattern.match(proxy_host):
        proxy_info = match.groupdict()

        proxy_url = (
            f"{proxy_info['protocol']}://"
            f"{proxy_info['host']}:{proxy_info['port'] or 80}"
        )

        proxy = {
            "server": proxy_url,
            "username": proxy_info["username"],
            "password": proxy_info["password"],
        }

    else:
        proxy_url = proxy_host
        proxy = {"server": proxy_url}

    if plugin_config.htmlrender_proxy_host_bypass:
        proxy["bypass"] = plugin_config.htmlrender_proxy_host_bypass

    return proxy


def with_lock(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    lock = Lock()

    @wraps(func)
    async def wrapper(*args, **kwargs) -> R:
        async with lock:
            return await func(*args, **kwargs)

    return wrapper


def _prepare_playwright_env_vars() -> None:
    """
    准备启动浏览器所需的环境变量。

    Returns:
        Dict[str, str]: 包含环境变量的字典
    """
    if (
        plugin_config.htmlrender_storage_path
        and not plugin_config.htmlrender_browser_executable_path
    ):
        storage_path = os.path.abspath(
            os.path.expanduser(str(plugin_config.htmlrender_storage_path))
        )
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = storage_path

        logger.debug(f'Setting PLAYWRIGHT_BROWSERS_PATH="{storage_path}"')


def _clear_playwright_env_vars() -> None:
    if (
        plugin_config.htmlrender_storage_path
        and not plugin_config.htmlrender_browser_executable_path
    ) and "PLAYWRIGHT_BROWSERS_PATH" in os.environ:
        playwright_path = os.environ.pop("PLAYWRIGHT_BROWSERS_PATH")
        logger.debug(f'PLAYWRIGHT_BROWSERS_PATH="{playwright_path}" removed')


def clean_playwright_cache() -> None:
    system = platform.system()
    home_dir = Path.home()
    cache_path = None

    if system == "Windows":
        cache_path = home_dir / "AppData" / "Local" / "ms-playwright"
    elif system == "Darwin":
        cache_path = home_dir / "Library" / "Caches" / "ms-playwright"
    elif system == "Linux":
        cache_path = home_dir / ".cache" / "ms-playwright"

    if cache_path and cache_path.exists():
        try:
            logger.warning(
                "Since v0.7.0, nonebot-plugin-htmlrender has moved the Playwright"
                "cache path. Executable files are now stored and managed by the "
                "`nonebot-plugin-localstore` plugin under "
                f"{plugin_config.htmlrender_storage_path}. "
                "You can change this path via the config option "
                "`htmlrender_storage_path`."
            )
            logger.info(f"Deleting Playwright directory at {cache_path}")
            shutil.rmtree(str(cache_path))
            logger.info("Playwright was cleaned successfully.")
        except Exception as e:
            logger.error(f"Failed to delete Playwright: {e}")
