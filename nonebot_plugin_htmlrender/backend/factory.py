from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module

from nonebot_plugin_htmlrender.consts import RenderBackend

from .base import Backend

BackendBuilder = Callable[[], Backend]
BackendAvailabilityChecker = Callable[[], "BackendAvailability"]


@dataclass(frozen=True)
class BackendAvailability:
    """后端运行环境检测结果。

    Attributes:
        available: 当前环境是否可用此后端。
        reason: 不可用时的原因描述，可用时为 ``None``。
    """

    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class RegisteredBackend:
    """注册表中的后端登记项。

    Attributes:
        builder: 用于构造后端实例的工厂函数。
        is_available: 调用后返回环境可用性的检测函数。
    """

    builder: BackendBuilder
    is_available: BackendAvailabilityChecker


_backend_registry: dict[RenderBackend, RegisteredBackend] = {}
_backend_loaders: dict[RenderBackend, tuple[str, str | None]] = {
    RenderBackend.PLAYWRIGHT: (
        "nonebot_plugin_htmlrender.backend.playwright.render",
        "register_playwright_backend",
    ),
    RenderBackend.TAKUMI: (
        "nonebot_plugin_htmlrender.backend.takumi.render",
        "register_takumi_backend",
    ),
}


@dataclass(frozen=True)
class BackendStatus:
    """对外暴露的后端状态描述。

    Attributes:
        backend: 后端标识。
        registered: 是否已经在注册表中登记。
        available: 当前运行环境是否可用此后端。
        reason: 不可用时的原因描述，可用时为 ``None``。
    """

    backend: RenderBackend
    registered: bool
    available: bool
    reason: str | None = None


def register_backend(
    backend: RenderBackend,
    builder: BackendBuilder,
    *,
    availability_checker: BackendAvailabilityChecker | None = None,
    force: bool = False,
) -> None:
    """注册渲染后端。

    Args:
        backend: 渲染后端标识。
        builder: 后端实例构建函数。
        availability_checker: 可用性检查函数，为 None 时默认返回可用。
        force: 为 True 时允许覆盖已注册的后端。

    Raises:
        RuntimeError: 后端已注册且 force 为 False 时。
    """
    registered = _backend_registry.get(backend)
    registration = RegisteredBackend(
        builder=builder,
        is_available=availability_checker
        or (lambda: BackendAvailability(available=True)),
    )

    if registered is not None and registered != registration and not force:
        raise RuntimeError(f"Backend `{backend}` is already registered.")
    _backend_registry[backend] = registration


def ensure_backend_loaded(backend: RenderBackend) -> None:
    """Load the implementation module for a backend when the package provides one."""
    if backend in _backend_registry:
        return

    loader = _backend_loaders.get(backend)
    if loader is None:
        return

    module_name, register_name = loader
    module = import_module(module_name)
    register = (
        getattr(module, register_name, None) if register_name is not None else None
    )
    if backend not in _backend_registry and callable(register):
        register()


def registered_backends() -> tuple[RenderBackend, ...]:
    """返回已注册的渲染后端列表。"""
    return tuple(sorted(_backend_registry, key=lambda item: item.value))


def get_backend_status(backend: RenderBackend) -> BackendStatus:
    """获取指定后端的注册和可用性状态。

    Args:
        backend: 渲染后端标识。

    Returns:
        包含注册状态、可用性和原因的 BackendStatus。
    """
    ensure_backend_loaded(backend)
    registered = _backend_registry.get(backend)
    if registered is None:
        return BackendStatus(
            backend=backend,
            registered=False,
            available=False,
            reason="Backend is not registered.",
        )

    try:
        availability = registered.is_available()
    except Exception as e:
        return BackendStatus(
            backend=backend,
            registered=True,
            available=False,
            reason=f"Availability check failed: {e}",
        )

    return BackendStatus(
        backend=backend,
        registered=True,
        available=availability.available,
        reason=availability.reason,
    )


def backend_statuses() -> tuple[BackendStatus, ...]:
    """返回所有渲染后端的状态信息。"""
    return tuple(get_backend_status(backend) for backend in sorted(RenderBackend))


def is_backend_registered(backend: RenderBackend) -> bool:
    """检查指定后端是否已注册。"""
    ensure_backend_loaded(backend)
    return backend in _backend_registry


def available_backends() -> tuple[RenderBackend, ...]:
    """返回当前可用的渲染后端列表。"""
    return tuple(status.backend for status in backend_statuses() if status.available)


def unavailable_backends() -> tuple[RenderBackend, ...]:
    """返回当前不可用的渲染后端列表。"""
    return tuple(
        status.backend for status in backend_statuses() if not status.available
    )


def is_backend_available(backend: RenderBackend) -> bool:
    """检查指定后端是否可用。"""
    return get_backend_status(backend).available
