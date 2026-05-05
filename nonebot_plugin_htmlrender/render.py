from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager, Protocol, Self, runtime_checkable

from nonebot.log import logger
from playwright.async_api import Browser, Page

from nonebot_plugin_htmlrender.backend import (
    PlaywrightMode,
    PlaywrightRender,
    Renderer,
    RenderRuntime,
    RenderSession,
)
from nonebot_plugin_htmlrender.telemetry import track_render
from nonebot_plugin_htmlrender.utils import suppress_and_log, with_lock


@runtime_checkable
class SupportsPageRender(Protocol):
    def get_new_page(
        self,
        session: RenderSession[Any, Any],
        device_scale_factor: float = 2,
        **kwargs: Any,
    ) -> AsyncContextManager[Page]: ...


class RenderLifecycleManager:
    def __init__(self, render: Renderer[Any, Any] | None = None) -> None:
        self._render: Renderer[Any, Any] = render or PlaywrightRender()
        self._runtime: RenderRuntime[Any] | None = None
        self._session: RenderSession[Any, Any] | None = None

    @asynccontextmanager
    async def get_new_page(
        self, device_scale_factor: float = 2, **kwargs: Any
    ) -> AsyncIterator[Page]:
        session = await self.get_render(**kwargs)
        if not isinstance(self._render, SupportsPageRender):
            raise RuntimeError(
                f"Renderer `{type(self._render).__name__}` does not support page operations."
            )
        async with track_render(
            "render.get_new_page",
            backend=self._render.backend,
        ), self._render.get_new_page(
            session,
            device_scale_factor=device_scale_factor,
            **kwargs,
        ) as page:
            yield page

    @with_lock
    async def get_render(self, **kwargs: Any) -> RenderSession[Any, Any]:
        session = self._session
        if session is not None and self._render.is_alive(session):
            return session

        return await self.startup_render(**kwargs)

    @with_lock
    async def startup_render(self, **kwargs: Any) -> RenderSession[Any, Any]:
        await self.shutdown_render()
        try:
            async with track_render("render.startup", backend=self._render.backend):
                for step in self._render.startup_steps():
                    await step()
                runtime = await self._render.open_runtime()
                self._runtime = runtime
                session = await self._render.open_session(runtime, **kwargs)
                self._session = session
        except Exception as e:
            logger.exception("Failed to initialize render session.")
            await self.shutdown_render()
            raise RuntimeError("Failed to initialize render session.") from e

        return session

    async def shutdown_render(self) -> None:
        session = self._session
        runtime = self._runtime
        self.clear_state()

        if session is not None:
            with suppress_and_log():
                await session.aclose()
        if runtime is not None:
            with suppress_and_log():
                await runtime.aclose()

    def clear_state(self) -> None:
        self._session = None
        self._runtime = None


class RenderRegistry:
    def __init__(self) -> None:
        self._managers: set[RenderLifecycleManager] = set()

    def register(self, manager: RenderLifecycleManager) -> RenderLifecycleManager:
        self._managers.add(manager)
        return manager

    def unregister(self, manager: RenderLifecycleManager) -> None:
        self._managers.discard(manager)

    async def shutdown_all(self) -> None:
        managers = list(self._managers)
        self._managers.clear()
        for manager in managers:
            await manager.shutdown_render()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.shutdown_all()


_default_registry = RenderRegistry()


class _ManagerState:
    def __init__(self) -> None:
        self.default_manager: RenderLifecycleManager | None = None


_state = _ManagerState()


def create_render_manager(
    *,
    register: bool = True,
    render: Renderer[Any, Any] | None = None,
    registry: RenderRegistry | None = None,
) -> RenderLifecycleManager:
    manager = RenderLifecycleManager(render=render)
    if register:
        target_registry = registry or _default_registry
        target_registry.register(manager)
    return manager


def get_default_render_manager() -> RenderLifecycleManager:
    if _state.default_manager is None:
        manager = create_render_manager()
        _state.default_manager = manager
        return manager
    return _state.default_manager


def get_render_registry() -> RenderRegistry:
    return _default_registry


async def shutdown_all_render_managers() -> None:
    await _default_registry.shutdown_all()
    _state.default_manager = None


class _DefaultManagerProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(get_default_render_manager(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(get_default_render_manager(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(get_default_render_manager(), name)


_manager = _DefaultManagerProxy()


@asynccontextmanager
async def get_new_page(
    device_scale_factor: float = 2, **kwargs: Any
) -> AsyncIterator[Page]:
    async with _manager.get_new_page(
        device_scale_factor=device_scale_factor,
        **kwargs,
    ) as page:
        yield page


async def get_render(**kwargs: Any) -> RenderSession[Any, Any]:
    return await _manager.get_render(**kwargs)


def _require_browser_target(session: RenderSession[Any, Any]) -> Browser:
    handle = session.handle
    if isinstance(handle, Browser):
        return handle
    raise RuntimeError("Current render target is not a Browser instance.")


async def startup_render(**kwargs: Any) -> RenderSession[Any, Any]:
    return await _manager.startup_render(**kwargs)


async def shutdown_render() -> None:
    if _state.default_manager is None:
        return
    await _state.default_manager.shutdown_render()


def _clear_globals() -> None:
    if _state.default_manager is not None:
        _state.default_manager.clear_state()
    _state.default_manager = None


# Backward compatible aliases
RenderEndpointLifecycleManager = RenderLifecycleManager
RenderEndpointRegistry = RenderRegistry
create_render_endpoint_manager = create_render_manager
get_default_render_endpoint_manager = get_default_render_manager
get_render_endpoint_registry = get_render_registry
shutdown_all_render_endpoint_managers = shutdown_all_render_managers
get_render_endpoint = get_render
startup_render_endpoint = startup_render
shutdown_render_endpoint = shutdown_render

BrowserLifecycleManager = RenderLifecycleManager
BrowserManagerRegistry = RenderRegistry
ConnectionType = PlaywrightMode
create_browser_manager = create_render_manager
get_default_browser_manager = get_default_render_manager
get_browser_manager_registry = get_render_registry
shutdown_all_browser_managers = shutdown_all_render_managers


async def get_browser(**kwargs: Any) -> Browser:
    session = await get_render(**kwargs)
    return _require_browser_target(session)


async def startup_htmlrender(**kwargs: Any) -> Browser:
    session = await startup_render(**kwargs)
    return _require_browser_target(session)


shutdown_htmlrender = shutdown_render
