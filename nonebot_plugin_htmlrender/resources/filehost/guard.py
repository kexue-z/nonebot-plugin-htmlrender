"""Filehost request authentication and FastAPI middleware."""

from __future__ import annotations  # noqa: I001

import hashlib
from collections.abc import Awaitable, Callable  # noqa: TC003
from importlib import import_module
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from starlette.responses import Response  # noqa: TC002
from nonebot import get_driver
from nonebot.drivers import ASGIMixin
from nonebot.log import logger

from nonebot_plugin_htmlrender.resources.config import get_resource_config

_FILEHOST_GUARD_STATE: dict[str, str | bool | None] = {
    "installed": False,
    "token": None,
}
_FILEHOST_FALLBACK_INSTANCE_ID = f"uuid4:{uuid.uuid4().hex}"


def _is_valid_guard_token(incoming: str | None) -> bool:
    """验证传入的请求头 token 是否与预期值匹配。"""
    if not incoming:
        return False
    return incoming == _FILEHOST_GUARD_STATE["token"]


def _get_request_guard_header_config() -> tuple[str, str]:
    """获取请求守卫的 header 名称和 token 值。"""
    cfg = get_resource_config()
    header_name = cfg.filehost_request_header_name.strip()
    if not header_name:
        header_name = "X-HTMLRender-Filehost-Request"

    if cfg.filehost_request_header_value is not None:
        token = cfg.filehost_request_header_value.strip()
        _FILEHOST_GUARD_STATE["token"] = token
    else:
        token = _derive_device_guard_token()
        _FILEHOST_GUARD_STATE["token"] = token

    return header_name, str(token)


def _resolve_device_identifier() -> str | None:
    """解析设备唯一标识符，用于生成守卫 token。"""
    try:
        machineid = import_module("machineid")
    except Exception:
        machineid = None

    if machineid is not None:
        try:
            value = machineid.id()
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception as e:
            logger.debug(f"Failed to get machineid.id(): {e}")

    try:
        mac = uuid.getnode()
    except Exception:
        return _FILEHOST_FALLBACK_INSTANCE_ID

    if mac:
        return f"mac:{mac:012x}"
    return _FILEHOST_FALLBACK_INSTANCE_ID


def _derive_device_guard_token() -> str:
    """基于设备标识和盐值派生守卫 token。"""
    cfg = get_resource_config()
    token_salt = cfg.filehost_request_header_salt
    return hashlib.sha256(
        f"{token_salt}:{_resolve_device_identifier() or 'unknown-device'}".encode()
    ).hexdigest()


def get_filehost_request_headers() -> dict[str, str]:
    """获取 filehost 请求所需的认证头字典。"""
    from nonebot_plugin_htmlrender.resources.filehost import (  # noqa: PLC0415
        _is_filehost_resolution_enabled,
    )

    enabled, _ = _is_filehost_resolution_enabled()
    if not enabled:
        return {}
    header_name, header_value = _get_request_guard_header_config()
    return {header_name: header_value}


def ensure_filehost_request_guard_installed(*, reason: str) -> bool:
    """确保 filehost 请求守卫中间件已安装到 FastAPI 应用。

    Args:
        reason: 安装原因，用于日志记录。

    Returns:
        中间件安装成功返回 True，否则返回 False。
    """
    if _FILEHOST_GUARD_STATE["installed"]:
        return True

    try:
        driver = get_driver()
    except Exception as e:
        logger.warning(
            f"Filehost request guard unavailable ({reason}): driver is not ready: {e}"
        )
        return False

    if not isinstance(driver, ASGIMixin):
        logger.warning(
            f"Filehost request guard unavailable ({reason}): driver is not ASGI-based."
        )
        return False

    app = driver.server_app
    if not isinstance(app, FastAPI):
        logger.warning(
            f"Filehost request guard unavailable ({reason}): server app is not FastAPI."
        )
        return False

    header_name, _ = _get_request_guard_header_config()

    try:

        @app.middleware("http")
        async def _htmlrender_filehost_guard(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            if request.url.path.startswith("/filehost/"):
                current_header_name, _ = _get_request_guard_header_config()
                incoming = request.headers.get(current_header_name)
                if not _is_valid_guard_token(incoming):
                    return PlainTextResponse(
                        "Forbidden: missing or invalid filehost request header.",
                        status_code=403,
                    )
            return await call_next(request)

    except RuntimeError as e:
        logger.warning(
            f"Filehost request guard unavailable ({reason}): middleware install failed: {e}"
        )
        return False

    _FILEHOST_GUARD_STATE["installed"] = True
    logger.info(
        f"Filehost request guard enabled ({reason}) with header {header_name!r}."
    )
    return True
