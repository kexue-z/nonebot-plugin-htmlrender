"""Filehost prewarming, directory registration, and bootstrap orchestration."""

from __future__ import annotations

from functools import partial
from importlib.util import find_spec
from pathlib import Path

import anyio
from anyio.to_thread import run_sync
from nonebot import require
from nonebot.log import logger

from nonebot_plugin_htmlrender.resources.config import get_resource_config

from .cache import (
    _FILEHOST_LEASES,
    _FILEHOST_RESOURCE_CACHE,
    filehost_url,
)
from .guard import ensure_filehost_request_guard_installed

_FILEHOST_PREWARM_LOCK = anyio.Lock()
_FILEHOST_PREWARM_STATE: dict[str, str | None] = {
    "url": None,
    "last_error": None,
}
_FILEHOST_PREWARM_PAYLOAD = b"nonebot-plugin-htmlrender:filehost-prewarm"
_FILEHOST_REGISTERED_ROOTS: set[Path] = set()
_TEMPLATE_FILE_SUFFIXES = {".html", ".htm", ".jinja", ".jinja2", ".tmpl", ".tpl"}


def _prewarm_enabled() -> bool:
    """检查 filehost 预热功能是否启用。"""
    cfg = get_resource_config()
    return bool(cfg.filehost_prewarm_enabled and cfg.filehost_prewarm_max_files > 0)


def _is_template_file(path: Path) -> bool:
    """判断路径是否为模板文件。"""
    return path.suffix.lower() in _TEMPLATE_FILE_SUFFIXES


def _should_prewarm_path(path: Path, extensions: set[str]) -> bool:
    """判断路径是否应参与预热（排除模板文件和不匹配的扩展名）。"""
    if not path.is_file():
        return False
    if _is_template_file(path):
        return False
    if not extensions:
        return True
    return path.suffix.lower() in extensions


def register_filehost_resource_root(path: str | Path) -> Path:
    """注册 filehost 资源根目录，用于预热扫描。

    Args:
        path: 资源根目录路径。

    Returns:
        规范化后的绝对路径。
    """
    resolved = Path(path).expanduser().resolve()
    _FILEHOST_REGISTERED_ROOTS.add(resolved)
    return resolved


def ensure_filehost_plugin_loaded(*, reason: str, strict: bool = False) -> bool:
    """确保 filehost 插件已加载。

    Args:
        reason: 加载原因，用于日志记录。
        strict: 为 True 时加载失败将抛出异常。

    Returns:
        插件加载成功返回 True，否则返回 False。
    """
    if find_spec("nonebot_plugin_filehost") is None:
        logger.debug(
            f"Skipping filehost plugin bootstrap ({reason}): nonebot_plugin_filehost not installed."
        )
        return False

    try:
        require("nonebot_plugin_filehost")
        from nonebot_plugin_htmlrender._bootstrap import (  # noqa: PLC0415
            _patch_filehost_request_headers_validator,
        )

        _patch_filehost_request_headers_validator()
    except Exception as e:
        _FILEHOST_PREWARM_STATE["last_error"] = str(e)
        if strict:
            raise RuntimeError(
                f"Filehost plugin bootstrap failed ({reason}): {e}"
            ) from e
        logger.warning(f"Filehost plugin bootstrap failed ({reason}): {e}")
        return False

    logger.debug(f"Filehost plugin bootstrap ready ({reason}).")
    return True


def _collect_prewarm_roots() -> list[Path]:
    """收集所有需要预热的资源根目录。"""
    cfg = get_resource_config()
    roots: set[Path] = set()
    roots.update(Path(p).expanduser().resolve() for p in cfg.filehost_allowed_paths)
    roots.update(Path(p).expanduser().resolve() for p in cfg.filehost_prewarm_paths)
    roots.update(_FILEHOST_REGISTERED_ROOTS)
    return [root for root in roots if root.exists() and root.is_dir()]


def _collect_prewarm_candidates(
    roots: list[Path],
    *,
    extensions: set[str],
    max_files: int,
) -> list[Path]:
    """收集预热候选文件列表，按目录递归扫描。"""
    candidates: list[Path] = []
    for root in roots:
        for candidate in root.rglob("*"):
            if len(candidates) >= max_files:
                return candidates
            if _should_prewarm_path(candidate, extensions):
                candidates.append(candidate)
    return candidates


async def _prewarm_resource_directories(*, reason: str) -> tuple[int, int]:
    """预热资源目录中的文件，将其上传至 filehost 缓存。

    Args:
        reason: 预热原因，用于日志记录。

    Returns:
        元组 (扫描文件数, 成功预热文件数)。
    """
    if not _prewarm_enabled():
        return (0, 0)

    cfg = get_resource_config()
    max_files = int(cfg.filehost_prewarm_max_files)
    extensions = {ext.lower() for ext in cfg.filehost_prewarm_extensions}
    roots = _collect_prewarm_roots()
    if not roots:
        return (0, 0)

    candidates = await run_sync(
        partial(
            _collect_prewarm_candidates,
            roots,
            extensions=extensions,
            max_files=max_files,
        )
    )
    warmed = 0
    warmed_lock = anyio.Lock()
    limiter = anyio.CapacityLimiter(min(8, max(1, len(candidates))))

    async def _prewarm_one(candidate: Path) -> None:
        nonlocal warmed
        async with limiter:
            try:
                await filehost_url(candidate)
                async with warmed_lock:
                    warmed += 1
            except Exception as e:
                logger.warning(
                    f"Filehost directory prewarm skipped {candidate!s} ({reason}): {e}"
                )

    async with anyio.create_task_group() as tg:
        for candidate in candidates:
            tg.start_soon(_prewarm_one, candidate)

    return len(candidates), warmed


async def ensure_filehost_runtime_ready(*, reason: str) -> bool:
    """确保 filehost 运行时已就绪（插件加载、守卫安装、资源预热）。

    Args:
        reason: 初始化原因，用于日志记录。

    Returns:
        运行时就绪返回 True，否则返回 False。
    """
    from nonebot_plugin_htmlrender.resources.filehost import (  # noqa: PLC0415
        _is_filehost_resolution_enabled,
    )

    try:
        enabled, status = _is_filehost_resolution_enabled()
    except Exception as e:
        logger.warning(f"Skipping filehost prewarm ({reason}): invalid config: {e}")
        return False

    if not enabled:
        logger.debug(f"Skipping filehost prewarm ({reason}): {status}")
        return False

    async with _FILEHOST_PREWARM_LOCK:
        if _FILEHOST_PREWARM_STATE["url"] is not None:
            logger.debug(
                f"Filehost prewarm already ready ({reason}): {_FILEHOST_PREWARM_STATE['url']}"
            )
            return True

        if not ensure_filehost_plugin_loaded(reason=reason):
            return False
        guard_ready = ensure_filehost_request_guard_installed(reason=reason)
        if not guard_ready:
            _FILEHOST_PREWARM_STATE["last_error"] = (
                "filehost request guard is not available for current driver/runtime."
            )
            logger.error(
                "Filehost request guard install failed; refusing to continue with "
                "filehost-enabled resource resolution."
            )
            return False

        logger.info(f"Prewarming filehost runtime ({reason}) with {status}")
        try:
            _FILEHOST_PREWARM_STATE["url"] = await filehost_url(
                _FILEHOST_PREWARM_PAYLOAD
            )
            _FILEHOST_PREWARM_STATE["last_error"] = None
            scanned, warmed = await _prewarm_resource_directories(reason=reason)
            if scanned > 0:
                logger.info(
                    "Filehost directory prewarm finished "
                    f"({reason}): scanned={scanned}, warmed={warmed}."
                )
        except Exception as e:
            _FILEHOST_PREWARM_STATE["last_error"] = str(e)
            logger.warning(f"Filehost prewarm failed ({reason}): {e}")
            return False

        logger.info(
            f"Filehost prewarm ready ({reason}): {_FILEHOST_PREWARM_STATE['url']}"
        )
        return True


def get_filehost_prewarm_status() -> dict[str, str | None]:
    """获取 filehost 预热状态信息字典。"""
    return {
        "ready": "true" if _FILEHOST_PREWARM_STATE["url"] is not None else "false",
        "url": _FILEHOST_PREWARM_STATE["url"],
        "last_error": _FILEHOST_PREWARM_STATE["last_error"],
        "cached_resources": str(len(_FILEHOST_RESOURCE_CACHE)),
        "active_leases": str(len(_FILEHOST_LEASES)),
    }
