from __future__ import annotations

from contextlib import asynccontextmanager
from enum import Enum
from importlib import import_module
import os
from typing import TYPE_CHECKING, Any
from typing_extensions import Unpack

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    import resource as _resource_mod

    from nonebot_plugin_htmlrender.backend.factory import BackendStatus
    from nonebot_plugin_htmlrender.backend.playwright.models import (
        HtmlRenderRequest,
        TemplateConfig,
        TemplateRenderRequest,
    )
    from nonebot_plugin_htmlrender.backend.playwright.types import (
        BrowserSessionKwargs,
        CaptureElementKwargs,
        PageContextKwargs,
        RenderHtmlKwargs,
        RenderMarkdownKwargs,
        RenderTemplateKwargs,
        RenderTextKwargs,
    )
    from nonebot_plugin_htmlrender.consts import RenderBackend

_resource_getrusage: Callable[[int], _resource_mod.struct_rusage] | None = None
_resource_rusage_self: int | None = None
if os.name == "posix":
    try:
        import resource as imported_resource
    except ImportError:
        pass
    else:
        _resource_getrusage = imported_resource.getrusage
        _resource_rusage_self = imported_resource.RUSAGE_SELF

from nonebot.log import logger

from nonebot_plugin_htmlrender.backend import (
    Backend,
    BackendCapability,
    RenderRuntime,
    RenderSession,
    SupportsHtmlRenderBackend,
    build_backend,
)
from nonebot_plugin_htmlrender.backend import (
    available_backends as backend_available_backends,
)
from nonebot_plugin_htmlrender.backend import (
    backend_statuses as backend_status_items,
)
from nonebot_plugin_htmlrender.backend import (
    get_backend_status as backend_get_status,
)
from nonebot_plugin_htmlrender.backend import (
    is_backend_available as backend_is_available,
)
from nonebot_plugin_htmlrender.backend import (
    is_backend_registered as backend_is_registered,
)
from nonebot_plugin_htmlrender.backend import (
    registered_backends as backend_registered_backends,
)
from nonebot_plugin_htmlrender.utils import suppress_and_log, track_render, with_lock

UnknownBackend = Backend
UnknownRuntime = RenderRuntime
UnknownSession = RenderSession


class StrEnum(str, Enum):
    """字符串枚举基类，用于声明取值为字符串的枚举类型。"""


class RenderCapability(StrEnum):
    """User-facing capabilities exposed by a render instance.

    A Render advertises these capabilities to upper layers. They describe
    "what this render can do" rather than how a concrete backend implements it.
    """

    CONTEXT = "context"
    """Create a render context for one render operation."""

    HTML_RENDER = "html_render"
    """Render HTML-oriented content."""

    TEXT_RENDER = "text_render"
    """Render plain text content into image output."""

    MARKDOWN_RENDER = "markdown_render"
    """Render Markdown content into image output."""

    TEMPLATE_RENDER = "template_render"
    """Render template content into image output."""

    TEMPLATE_HTML_RENDER = "template_html_render"
    """Render template content into raw HTML output."""

    HTML_ELEMENT_CAPTURE = "html_element_capture"
    """Capture a specific HTML element into image output."""

    RASTER_RENDER = "raster_render"
    """Render raster/image-oriented content."""


_RENDER_TO_BACKEND_CAPABILITIES: dict[
    RenderCapability, frozenset[BackendCapability]
] = {
    RenderCapability.CONTEXT: frozenset({BackendCapability.RENDER_CONTEXT}),
    RenderCapability.HTML_RENDER: frozenset(
        {
            BackendCapability.RENDER_CONTEXT,
            BackendCapability.HTML_RENDER,
        }
    ),
    RenderCapability.TEXT_RENDER: frozenset(
        {
            BackendCapability.RENDER_CONTEXT,
            BackendCapability.HTML_RENDER,
            BackendCapability.TEXT_RENDER,
        }
    ),
    RenderCapability.MARKDOWN_RENDER: frozenset(
        {
            BackendCapability.RENDER_CONTEXT,
            BackendCapability.HTML_RENDER,
            BackendCapability.MARKDOWN_RENDER,
        }
    ),
    RenderCapability.TEMPLATE_RENDER: frozenset(
        {
            BackendCapability.RENDER_CONTEXT,
            BackendCapability.HTML_RENDER,
            BackendCapability.TEMPLATE_RENDER,
        }
    ),
    RenderCapability.TEMPLATE_HTML_RENDER: frozenset(
        {BackendCapability.TEMPLATE_HTML_RENDER}
    ),
    RenderCapability.HTML_ELEMENT_CAPTURE: frozenset(
        {
            BackendCapability.RENDER_CONTEXT,
            BackendCapability.HTML_RENDER,
            BackendCapability.HTML_ELEMENT_CAPTURE,
        }
    ),
    RenderCapability.RASTER_RENDER: frozenset({BackendCapability.RASTER_RENDER}),
}


def _build_default_backend() -> UnknownBackend:
    """构建默认渲染后端实例。"""
    return build_backend()


class Render:
    """统一的渲染门面。

    将上层调用方暴露的渲染能力封装在 ``Render`` 实例中，内部委托给具体的
    渲染后端完成实际工作。同一个进程通常只持有一个默认 ``Render`` 实例。
    """

    def __init__(self, backend: UnknownBackend | None = None) -> None:
        """初始化 Render 实例。

        Args:
            backend: 渲染后端实例，为 None 时使用默认后端。
        """
        self._backend: UnknownBackend = backend or _build_default_backend()
        self._runtime: UnknownRuntime | None = None
        self._session: UnknownSession | None = None

    @property
    def backend(self) -> UnknownBackend:
        return self._backend

    @property
    def backend_capabilities(self) -> frozenset[BackendCapability]:
        """Low-level capabilities declared by the bound backend."""
        return self._backend.capabilities

    @property
    def capabilities(self) -> frozenset[RenderCapability]:
        """User-facing capabilities available on this render instance."""
        return frozenset(
            capability
            for capability, requirements in _RENDER_TO_BACKEND_CAPABILITIES.items()
            if requirements.issubset(self._backend.capabilities)
        )

    def has_backend_capability(self, capability: BackendCapability) -> bool:
        """Check whether the bound backend exposes a low-level capability."""
        return capability in self._backend.capabilities

    def has_capability(self, capability: RenderCapability) -> bool:
        """Check whether this render instance exposes a user-facing capability."""
        return capability in self.capabilities

    def _require_html_backend(
        self,
        capability: RenderCapability,
    ) -> SupportsHtmlRenderBackend:
        """校验并返回支持 HTML 渲染的后端。

        Args:
            capability: 需要校验的渲染能力。

        Returns:
            支持 HTML 渲染操作的后端实例。

        Raises:
            RuntimeError: 当后端不支持指定能力或未实现 HTML 渲染操作时。
        """
        if not self.has_capability(capability):
            raise RuntimeError(
                f"Render `{type(self).__name__}` does not support "
                f"`{capability.value}` capability."
            )

        backend = self._backend
        if not isinstance(backend, SupportsHtmlRenderBackend):
            raise RuntimeError(
                f"Backend `{type(backend).__name__}` declares html_render but does not "
                "implement HTML render operations."
            )
        return backend

    @asynccontextmanager
    async def get_render_context(
        self,
        **kwargs: Unpack[PageContextKwargs],
    ) -> AsyncIterator[object]:
        """获取渲染上下文。

        作为异步上下文管理器使用，在上下文中提供一次渲染操作所需的页面上下文。

        Args:
            **kwargs: 页面上下文配置参数。

        Yields:
            渲染上下文对象。

        Raises:
            RuntimeError: 当后端不支持上下文能力时。
        """
        if not self.has_capability(RenderCapability.CONTEXT):
            raise RuntimeError(
                f"Render `{type(self).__name__}` does not support context capability."
            )
        session = await self.get_render()
        async with (
            track_render(
                "render.get_render_context",
                backend=self._backend.backend,
                attrs=_get_render_observation_attrs(self),
            ),
            self._backend.get_render_context(session, **kwargs) as context,
        ):
            yield context

    async def render_html(
        self,
        request: HtmlRenderRequest | str,
        **kwargs: Unpack[RenderHtmlKwargs],
    ) -> bytes:
        """将 HTML 内容渲染为图片。

        Args:
            request: HTML 渲染请求对象或 HTML 字符串。
            **kwargs: 额外的 HTML 渲染参数。

        Returns:
            渲染生成的图片字节数据。
        """
        session = await self.get_render()
        return await self._require_html_backend(
            RenderCapability.HTML_RENDER
        ).render_html(
            session,
            request,
            **kwargs,
        )

    async def render_text(
        self,
        text: str,
        **kwargs: Unpack[RenderTextKwargs],
    ) -> bytes:
        """将纯文本渲染为图片。

        Args:
            text: 待渲染的纯文本内容。
            **kwargs: 额外的文本渲染参数。

        Returns:
            渲染生成的图片字节数据。
        """
        session = await self.get_render()
        return await self._require_html_backend(
            RenderCapability.TEXT_RENDER
        ).render_text(
            session,
            text,
            **kwargs,
        )

    async def render_markdown(
        self,
        markdown_text: str = "",
        **kwargs: Unpack[RenderMarkdownKwargs],
    ) -> bytes:
        """将 Markdown 内容渲染为图片。

        Args:
            markdown_text: 待渲染的 Markdown 文本。
            **kwargs: 额外的 Markdown 渲染参数。

        Returns:
            渲染生成的图片字节数据。
        """
        session = await self.get_render()
        return await self._require_html_backend(
            RenderCapability.MARKDOWN_RENDER
        ).render_markdown(session, markdown_text, **kwargs)

    async def render_template(
        self,
        request: TemplateRenderRequest | str,
        **kwargs: Unpack[RenderTemplateKwargs],
    ) -> bytes:
        """将模板内容渲染为图片。

        Args:
            request: 模板渲染请求对象或模板名称字符串。
            **kwargs: 额外的模板渲染参数。

        Returns:
            渲染生成的图片字节数据。
        """
        session = await self.get_render()
        return await self._require_html_backend(
            RenderCapability.TEMPLATE_RENDER
        ).render_template(session, request, **kwargs)

    async def render_template_html(
        self,
        template: TemplateConfig | str,
        **kwargs: Any,
    ) -> str:
        """将模板内容渲染为 HTML 字符串。

        Args:
            template: 模板配置对象或模板名称字符串。
            **kwargs: 传递给模板引擎的额外参数。

        Returns:
            渲染生成的 HTML 字符串。
        """
        return await self._require_html_backend(
            RenderCapability.TEMPLATE_HTML_RENDER
        ).render_template_html(template, **kwargs)

    async def capture_html_element(
        self,
        url: str,
        element: str,
        **kwargs: Unpack[CaptureElementKwargs],
    ) -> bytes:
        """捕获指定 URL 页面中的 HTML 元素并渲染为图片。

        Args:
            url: 目标页面的 URL。
            element: 要捕获的 HTML 元素选择器。
            **kwargs: 额外的元素捕获参数。

        Returns:
            捕获的元素图片字节数据。
        """
        session = await self.get_render()
        return await self._require_html_backend(
            RenderCapability.HTML_ELEMENT_CAPTURE
        ).capture_html_element(session, url, element, **kwargs)

    @with_lock
    async def get_render(
        self,
        **kwargs: Unpack[BrowserSessionKwargs],
    ) -> UnknownSession:
        """获取或创建渲染会话。

        若当前会话仍然存活则复用，否则重新启动渲染运行时并创建新会话。

        Args:
            **kwargs: 浏览器会话配置参数。

        Returns:
            可用的渲染会话实例。
        """
        session = self._session
        if session is not None and self._backend.is_alive(session):
            async with track_render(
                "render.get_render",
                backend=self._backend.backend,
                attrs={
                    "render.cache_hit": "true",
                    **_get_render_observation_attrs(self),
                },
            ):
                return session

        async with track_render(
            "render.get_render",
            backend=self._backend.backend,
            attrs={
                "render.cache_hit": "false",
                **_get_render_observation_attrs(self),
            },
        ):
            return await self.startup_render(**kwargs)

    @with_lock
    async def startup_render(
        self,
        **kwargs: Unpack[BrowserSessionKwargs],
    ) -> UnknownSession:
        """启动渲染运行时并创建新的渲染会话。

        先关闭已有的运行时和会话，然后依次执行后端启动步骤、创建运行时和会话。

        Args:
            **kwargs: 浏览器会话配置参数。

        Returns:
            新创建的渲染会话实例。

        Raises:
            RuntimeError: 当初始化渲染会话失败时。
        """
        await self.shutdown_render()
        try:
            async with track_render(
                "render.startup",
                backend=self._backend.backend,
                attrs=_get_render_observation_attrs(self),
            ):
                for step in self._backend.startup_steps():
                    await step()
                runtime = await self._backend.create_runtime()
                self._runtime = runtime
                session = await self._backend.create_session(runtime, **kwargs)
                self._session = session
        except Exception as e:
            logger.exception("Failed to initialize render session.")
            await self.shutdown_render()
            raise RuntimeError("Failed to initialize render session.") from e

        return session

    async def probe_render(self) -> None:
        """执行最小化渲染探测。"""
        if not self.has_capability(RenderCapability.CONTEXT):
            await self.get_render()
            return

        async with self.get_render_context():
            return

    async def shutdown_render(self) -> None:
        """关闭渲染运行时并释放相关资源。"""
        async with track_render(
            "render.shutdown",
            backend=self._backend.backend,
            attrs=_get_render_observation_attrs(self),
        ):
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
        """清除内部状态引用，将会话和运行时置为 None。"""
        self._session = None
        self._runtime = None


def _get_render_observation_attrs(render: Render | None = None) -> dict[str, str]:
    """构建渲染可观测性属性字典。

    Args:
        render: Render 实例，为 None 时仅包含进程级指标。

    Returns:
        包含运行时状态和内存占用等可观测性属性的字典。
    """
    attrs: dict[str, str] = {}
    if render is not None:
        attrs["render.runtime.active"] = str(render._runtime is not None).lower()
        attrs["render.session.active"] = str(render._session is not None).lower()

    rss_mb = _get_process_rss_mb()
    if rss_mb is not None:
        attrs["render.process.rss_mb"] = f"{rss_mb:.2f}"
    return attrs


def _get_process_rss_mb() -> float | None:  # pragma: no cover
    """获取当前进程的 RSS 内存占用，单位为 MB。"""
    if _resource_getrusage is None or _resource_rusage_self is None:
        return None

    usage = _resource_getrusage(_resource_rusage_self)
    rss_value = getattr(usage, "ru_maxrss", 0)
    rss = rss_value if isinstance(rss_value, int | float) else 0
    rss_mb = rss / 1024 if rss > 0 else 0
    if hasattr(os, "uname") and "darwin" in os.uname().sysname.lower():
        rss_mb = rss / (1024 * 1024)
    return rss_mb


class _RenderState:
    def __init__(self) -> None:
        self.default_render: Render | None = None


_state = _RenderState()


def create_render(
    *,
    backend: UnknownBackend | None = None,
) -> Render:
    """创建新的 Render 实例。

    Args:
        backend: 渲染后端实例，为 None 时使用默认后端。

    Returns:
        新创建的 Render 实例。
    """
    return Render(backend=backend)


def available_render_backends() -> tuple[RenderBackend, ...]:
    """返回当前可用的渲染后端列表。"""
    return backend_available_backends()


def unavailable_render_backends() -> tuple[RenderBackend, ...]:
    """返回当前不可用的渲染后端列表。"""
    return tuple(
        status.backend
        for status in list_render_backend_statuses()
        if not status.available
    )


def registered_render_backends() -> tuple[RenderBackend, ...]:
    """返回已注册的渲染后端列表。"""
    return backend_registered_backends()


def get_render_backend_status(backend: RenderBackend) -> BackendStatus:
    """获取指定渲染后端的状态信息。

    Args:
        backend: 渲染后端标识。

    Returns:
        后端的状态信息。
    """
    return backend_get_status(backend)


def list_render_backend_statuses() -> tuple[BackendStatus, ...]:
    """列出所有渲染后端的状态信息。"""
    return backend_status_items()


def is_render_backend_available(backend: RenderBackend) -> bool:
    """检查指定渲染后端是否可用。

    Args:
        backend: 渲染后端标识。

    Returns:
        后端可用时返回 True。
    """
    return backend_is_available(backend)


def is_render_backend_registered(backend: RenderBackend) -> bool:
    """检查指定渲染后端是否已注册。

    Args:
        backend: 渲染后端标识。

    Returns:
        后端已注册时返回 True。
    """
    return backend_is_registered(backend)


def get_default_render() -> Render:
    """获取或创建默认的 Render 实例。"""
    if _state.default_render is None:
        render = create_render()
        _state.default_render = render
        return render
    return _state.default_render


@asynccontextmanager
async def get_render_context(
    **kwargs: Unpack[PageContextKwargs],
) -> AsyncIterator[object]:
    """使用默认 Render 实例获取渲染上下文。

    Args:
        **kwargs: 页面上下文配置参数。

    Yields:
        渲染上下文对象。
    """
    async with get_default_render().get_render_context(**kwargs) as context:
        yield context


async def get_render(**kwargs: Unpack[BrowserSessionKwargs]) -> UnknownSession:
    """使用默认 Render 实例获取渲染会话。"""
    return await get_default_render().get_render(**kwargs)


async def startup_render(**kwargs: Unpack[BrowserSessionKwargs]) -> UnknownSession:
    """使用默认 Render 实例启动渲染。"""
    return await get_default_render().startup_render(**kwargs)


async def probe_render() -> None:
    """使用默认 Render 实例执行最小化渲染探测。"""
    await get_default_render().probe_render()


async def shutdown_render() -> None:
    """关闭默认 Render 实例的渲染运行时。"""
    if _state.default_render is None:
        return
    await _state.default_render.shutdown_render()
    _state.default_render = None


async def render_html(
    request: HtmlRenderRequest | str,
    **kwargs: Unpack[RenderHtmlKwargs],
) -> bytes:
    """使用默认 Render 实例将 HTML 渲染为图片。"""
    return await get_default_render().render_html(request, **kwargs)


async def render_text(text: str, **kwargs: Unpack[RenderTextKwargs]) -> bytes:
    """使用默认 Render 实例将文本渲染为图片。"""
    return await get_default_render().render_text(text, **kwargs)


async def render_markdown(
    markdown_text: str = "",
    **kwargs: Unpack[RenderMarkdownKwargs],
) -> bytes:
    """使用默认 Render 实例将 Markdown 渲染为图片。"""
    return await get_default_render().render_markdown(markdown_text, **kwargs)


async def render_template(
    request: TemplateRenderRequest | str,
    **kwargs: Unpack[RenderTemplateKwargs],
) -> bytes:
    """使用默认 Render 实例将模板渲染为图片。"""
    return await get_default_render().render_template(request, **kwargs)


async def render_template_html(template: TemplateConfig | str, **kwargs: Any) -> str:
    """使用默认 Render 实例将模板渲染为 HTML。"""
    return await get_default_render().render_template_html(template, **kwargs)


async def capture_html_element(
    url: str,
    element: str,
    **kwargs: Unpack[CaptureElementKwargs],
) -> bytes:
    """使用默认 Render 实例捕获 HTML 元素截图。"""
    return await get_default_render().capture_html_element(url, element, **kwargs)


def create_png_config(*args: Any, **kwargs: Any) -> Any:
    """Create a PNG render config through the Playwright compatibility helper."""
    models = import_module("nonebot_plugin_htmlrender.backend.playwright.models")
    create_config = models.create_png_config

    return create_config(*args, **kwargs)


def create_jpeg_config(*args: Any, **kwargs: Any) -> Any:
    """Create a JPEG render config through the Playwright compatibility helper."""
    models = import_module("nonebot_plugin_htmlrender.backend.playwright.models")
    create_config = models.create_jpeg_config

    return create_config(*args, **kwargs)
