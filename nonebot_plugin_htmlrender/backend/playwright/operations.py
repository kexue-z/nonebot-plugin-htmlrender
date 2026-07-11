from contextlib import suppress
from importlib import import_module
from pathlib import Path
from typing import Any, Literal, cast
from typing_extensions import Unpack

from nonebot.log import logger

from nonebot_plugin_htmlrender.backend.playwright.config import get_playwright_config
from nonebot_plugin_htmlrender.consts import (
    RemoteLocalResourcePolicy,
    RenderBackend,
    ResourceResolveMode,
)
from nonebot_plugin_htmlrender.preparation import (
    TEMPLATES_PATH,
    prepare_markdown,
    prepare_text,
)
from nonebot_plugin_htmlrender.resources import (
    FileCachePolicy,
    ResourceResolver,
    is_remote_playwright_mode,
    read_resource_text,
    resolve_html_resources,
    resolve_template_vars,
)
from nonebot_plugin_htmlrender.resources.templating import (
    render_template_html as render_jinja_template_html,
)
from nonebot_plugin_htmlrender.utils import track_render

from ._page import (
    SupportsBrowserSession,
    _setup_page_logging,
    check_remote_pna_context,
    install_filehost_request_route,
    open_page_context,
    register_render_context_provider,
)
from .models import (
    ContentConfig,
    HtmlRenderRequest,
    JpegScreenshotOptions,
    PageConfig,
    RenderConfig,
    TemplateConfig,
    TemplateRenderRequest,
    ViewportConfig,
    _build_html_render_request,
    _build_screenshot_config,
    _build_template_render_request,
    _page_context_kwargs,
)
from .telemetry import log_page_telemetry
from .types import (
    GotoKwargs,
    HtmlPageKwargs,
    LocatorScreenshotKwargs,
    PageContextKwargs,
    TemplatePageKwargs,
)

EMPTY_PAGE_CONTEXT_KWARGS: PageContextKwargs = {}
EMPTY_GOTO_KWARGS: GotoKwargs = {}
EMPTY_LOCATOR_SCREENSHOT_KWARGS: LocatorScreenshotKwargs = {}


def create_filehost_lease() -> str:
    filehost = import_module("nonebot_plugin_htmlrender.resources.filehost")
    create_lease = filehost.create_filehost_lease

    return create_lease()


async def release_filehost_lease(lease_id: str) -> None:
    filehost = import_module("nonebot_plugin_htmlrender.resources.filehost")
    release_lease = filehost.release_filehost_lease

    await release_lease(lease_id)


def get_filehost_request_headers() -> dict[str, str]:
    filehost = import_module("nonebot_plugin_htmlrender.resources.filehost")
    get_headers = filehost.get_filehost_request_headers

    return get_headers()


def register_filehost_resource_root(path: str | Path) -> Path:
    filehost = import_module("nonebot_plugin_htmlrender.resources.filehost")
    register_root = filehost.register_filehost_resource_root

    return register_root(path)


def _enum_value(raw: object) -> str:
    """获取枚举值的字符串表示。"""
    return str(getattr(raw, "value", raw))


async def read_file(path: str) -> str:
    """异步读取文件内容。"""
    return await read_resource_text(path)


async def read_tpl(path: str) -> str:
    """读取模板目录下的文件内容。"""
    return await read_resource_text(
        TEMPLATES_PATH / path,
        policy=FileCachePolicy.IMMUTABLE,
    )


async def render_template_html(
    template: TemplateConfig | str,
    template_name: str | None = None,
    filters: dict[str, Any] | None = None,
    **kwargs: Any,
) -> str:
    """使用 Jinja2 渲染模板为 HTML 字符串。

    Args:
        template: 模板配置对象或模板目录路径。
        template_name: 模板文件名，当 template 为路径字符串时必须提供。
        filters: 自定义 Jinja2 过滤器字典。
        **kwargs: 传递给模板渲染的变量。

    Returns:
        渲染后的 HTML 字符串。

    Raises:
        ValueError: 当 template 为字符串且未提供 template_name 时。
    """
    if isinstance(template, TemplateConfig):
        template_path = template.template_path
        template_name = template.template_name
        filters = template.custom_filters or filters
        kwargs = {**template.template_vars, **kwargs}
    else:
        if template_name is None:
            raise ValueError("template_name is required when template is a path string")
        template_path = template

    return await render_jinja_template_html(
        template_path,
        template_name,
        kwargs,
        filters=filters,
    )


async def render_html(
    request: HtmlRenderRequest | str,
    wait: int = 0,
    template_path: str | None = None,
    image_type: Literal["jpeg", "png"] = "png",
    quality: int | None = None,
    device_scale_factor: float = 2,
    screenshot_timeout: float | None = 30_000,
    *,
    full_page: bool = True,
    session: SupportsBrowserSession | None = None,
    **kwargs: Unpack[HtmlPageKwargs],
) -> bytes:
    """将 HTML 内容渲染为截图图片。

    Args:
        request: HTML 渲染请求对象或 HTML 字符串。
        wait: 截图前的等待时间（毫秒）。
        template_path: 页面 base_url，用于解析相对路径资源。
        image_type: 输出图片格式。
        quality: JPEG 图片质量（0-100），仅 jpeg 格式有效。
        device_scale_factor: 设备像素比，控制图片清晰度。
        screenshot_timeout: 截图超时时间（毫秒）。
        full_page: 是否截取整个页面。
        session: 浏览器会话，为 None 时使用默认会话。
        **kwargs: 额外的页面配置参数。

    Returns:
        渲染生成的图片字节数据。
    """
    if isinstance(request, HtmlRenderRequest):
        render_request = request
    else:
        viewport = kwargs.pop("viewport", None)
        user_agent = kwargs.pop("user_agent", None)
        extra_http_headers = kwargs.pop("extra_http_headers", None)
        viewport_value = (
            cast("dict[str, int]", dict(viewport)) if viewport is not None else None
        )
        user_agent_value = user_agent if isinstance(user_agent, str) else None
        headers_value = (
            extra_http_headers
            if isinstance(extra_http_headers, dict)
            and all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in extra_http_headers.items()
            )
            else None
        )
        render_request = _build_html_render_request(
            request,
            template_path=template_path,
            image_type=image_type,
            quality=quality,
            device_scale_factor=device_scale_factor,
            screenshot_timeout=screenshot_timeout,
            full_page=full_page,
            wait=wait,
            viewport=viewport_value,
            user_agent=user_agent_value,
            extra_http_headers=headers_value,
        )

    async with (
        track_render(
            "playwright.html_render.render_html",
            backend=RenderBackend.PLAYWRIGHT,
        ),
        open_page_context(
            session=session,
            **cast(
                "PageContextKwargs",
                {**_page_context_kwargs(render_request.render), **kwargs},
            ),
        ) as page,
    ):
        if is_remote_playwright_mode() and (
            _enum_value(get_playwright_config().remote_local_resource_policy)
            == RemoteLocalResourcePolicy.FILEHOST.value
        ):
            await install_filehost_request_route(
                page,
                filehost_headers=get_filehost_request_headers(),
            )

        _setup_page_logging(page)
        await page.goto(render_request.render.page.base_url)
        await page.set_content(
            render_request.content.html,
            wait_until=render_request.content.wait_until,
        )
        await page.wait_for_timeout(render_request.content.additional_wait)
        await log_page_telemetry(page, op="playwright.html_render.render_html")
        screenshot = render_request.render.screenshot
        await page.wait_for_timeout(screenshot.wait_before_screenshot)
        if isinstance(screenshot, JpegScreenshotOptions):
            return await page.screenshot(
                full_page=screenshot.full_page,
                type=screenshot.format,
                quality=screenshot.quality,
                timeout=screenshot.timeout,
            )
        return await page.screenshot(
            full_page=screenshot.full_page,
            type=screenshot.format,
            timeout=screenshot.timeout,
        )


async def render_text(
    text: str,
    css_path: str = "",
    width: int = 500,
    image_type: Literal["jpeg", "png"] = "png",
    quality: int | None = None,
    device_scale_factor: float = 2,
    screenshot_timeout: float | None = 30_000,
    *,
    render: RenderConfig | None = None,
    session: SupportsBrowserSession | None = None,
) -> bytes:
    """将纯文本渲染为图片。

    Args:
        text: 待渲染的纯文本内容。
        css_path: 自定义 CSS 文件路径，为空时使用默认样式。
        width: 视口宽度（像素）。
        image_type: 输出图片格式。
        quality: JPEG 图片质量（0-100）。
        device_scale_factor: 设备像素比。
        screenshot_timeout: 截图超时时间（毫秒）。
        render: 自定义渲染配置，为 None 时自动构建。
        session: 浏览器会话。

    Returns:
        渲染生成的图片字节数据。
    """
    async with track_render(
        "playwright.html_render.render_text",
        backend=RenderBackend.PLAYWRIGHT,
    ):
        prepared = await prepare_text(text, css_path=css_path)

        render_request = HtmlRenderRequest(
            content=ContentConfig(html=prepared.html),
            render=render
            or RenderConfig(
                page=PageConfig(
                    viewport=ViewportConfig(width=width, height=10),
                    base_url=prepared.base_url or "about:blank",
                ),
                screenshot=_build_screenshot_config(
                    image_type,
                    quality=quality,
                    device_scale_factor=device_scale_factor,
                    screenshot_timeout=screenshot_timeout,
                    full_page=True,
                    wait_before_screenshot=0,
                ),
            ),
        )

        return await render_html(render_request, session=session)


async def render_markdown(
    md: str = "",
    md_path: str = "",
    css_path: str = "",
    width: int = 500,
    image_type: Literal["jpeg", "png"] = "png",
    quality: int | None = None,
    device_scale_factor: float = 2,
    screenshot_timeout: float | None = 30_000,
    *,
    render: RenderConfig | None = None,
    session: SupportsBrowserSession | None = None,
) -> bytes:
    """将 Markdown 内容渲染为图片。

    Args:
        md: Markdown 文本内容。
        md_path: Markdown 文件路径，与 md 二选一。
        css_path: 自定义 CSS 文件路径，为空时使用默认样式。
        width: 视口宽度（像素）。
        image_type: 输出图片格式。
        quality: JPEG 图片质量（0-100）。
        device_scale_factor: 设备像素比。
        screenshot_timeout: 截图超时时间（毫秒）。
        render: 自定义渲染配置。
        session: 浏览器会话。

    Returns:
        渲染生成的图片字节数据。

    Raises:
        ValueError: 当 md 和 md_path 均未提供时。
    """
    async with track_render(
        "playwright.html_render.render_markdown",
        backend=RenderBackend.PLAYWRIGHT,
    ):
        prepared = await prepare_markdown(
            md,
            markdown_path=md_path,
            css_path=css_path,
        )

        if render is None:
            base_url = prepared.base_url or "about:blank"
            if is_remote_playwright_mode():
                base_url = "about:blank"
            render = RenderConfig(
                page=PageConfig(
                    viewport=ViewportConfig(width=width, height=10),
                    base_url=_path_to_uri(css_path)
                    if css_path
                    else MARKDOWN_TEMPLATE_FILE.as_uri(),
                ),
                screenshot=_build_screenshot_config(
                    image_type,
                    quality=quality,
                    device_scale_factor=device_scale_factor,
                    screenshot_timeout=screenshot_timeout,
                    full_page=True,
                    wait_before_screenshot=0,
                ),
            )

        render_request = HtmlRenderRequest(
            content=ContentConfig(html=prepared.html),
            render=render,
        )

        return await render_html(render_request, session=session)


async def render_template(
    request: TemplateRenderRequest | str,
    template_name: str | None = None,
    templates: dict[str, Any] | None = None,
    filters: dict[str, Any] | None = None,
    pages: TemplatePageKwargs | None = None,
    wait: int = 0,
    image_type: Literal["jpeg", "png"] = "png",
    quality: int | None = None,
    device_scale_factor: float = 2,
    screenshot_timeout: float | None = 30_000,
    *,
    session: SupportsBrowserSession | None = None,
    resolve_resources: bool | None = None,
    resource_resolver: ResourceResolver | str | None = None,
    resource_strict: bool = False,
) -> bytes:
    """将 Jinja2 模板渲染为图片。

    支持资源解析和 filehost 模式，可自动将模板中引用的本地资源
    上传至 filehost 服务以供远程浏览器访问。

    Args:
        request: 模板渲染请求对象或模板目录路径。
        template_name: 模板文件名，当 request 为路径字符串时必须提供。
        templates: 传递给模板的变量字典。
        filters: 自定义 Jinja2 过滤器字典。
        pages: 页面配置（视口、base_url 等）。
        wait: 截图前的等待时间（毫秒）。
        image_type: 输出图片格式。
        quality: JPEG 图片质量（0-100）。
        device_scale_factor: 设备像素比。
        screenshot_timeout: 截图超时时间（毫秒）。
        session: 浏览器会话。
        resolve_resources: 是否解析模板资源，为 None 时根据配置决定。
        resource_resolver: 资源解析器，为 None 时使用自动检测。
        resource_strict: 资源解析失败时是否抛出异常。

    Returns:
        渲染生成的图片字节数据。

    Raises:
        ValueError: 当 request 为字符串且未提供 template_name 时。
    """
    async with track_render(
        "playwright.html_render.render_template",
        backend=RenderBackend.PLAYWRIGHT,
    ):
        if isinstance(request, TemplateRenderRequest):
            render_request = request
        else:
            if template_name is None:
                raise ValueError(
                    "template_name is required when request is a path string"
                )
            render_request = _build_template_render_request(
                request,
                template_name,
                template_vars=templates or {},
                custom_filters=filters,
                pages=pages,
                image_type=image_type,
                quality=quality,
                device_scale_factor=device_scale_factor,
                screenshot_timeout=screenshot_timeout,
                wait=wait,
            )

        # Register template root for filehost resource prewarm/indexing.
        with suppress(Exception):
            register_filehost_resource_root(render_request.template.template_path)

        should_resolve_resources = resolve_resources
        if should_resolve_resources is None:
            should_resolve_resources = (
                get_playwright_config().resource_resolve_mode != ResourceResolveMode.OFF
            )

        lease_id: str | None = (
            create_filehost_lease() if should_resolve_resources else None
        )
        try:
            if should_resolve_resources:
                vars_resolver: ResourceResolver | str = (
                    resource_resolver if resource_resolver is not None else "auto"
                )
                resolved_template_vars = await resolve_template_vars(
                    render_request.template.template_vars,
                    template_base=render_request.template.template_path,
                    strict=resource_strict,
                    resolver=vars_resolver,
                    lease_id=lease_id,
                )
                render_request = TemplateRenderRequest(
                    template=TemplateConfig(
                        template_path=render_request.template.template_path,
                        template_name=render_request.template.template_name,
                        template_vars=resolved_template_vars,
                        custom_filters=render_request.template.custom_filters,
                    ),
                    render=render_request.render,
                )

            if (
                is_remote_playwright_mode()
                and render_request.render.page.base_url.startswith("file://")
                and get_playwright_config().remote_local_resource_policy
                != RemoteLocalResourcePolicy.PASSTHROUGH
            ):
                logger.warning(
                    "Remote Playwright mode detected with `file://` base_url. "
                    "Use `about:blank` or an HTTP(S) base URL for remote resources."
                )

            if is_remote_playwright_mode():
                check_remote_pna_context(
                    base_url=render_request.render.page.base_url,
                    template_vars=render_request.template.template_vars,
                    strict=resource_strict,
                )

            rendered_html = await render_jinja_template_html(
                render_request.template.template_path,
                render_request.template.template_name,
                render_request.template.template_vars,
                filters=render_request.template.custom_filters,
            )

            if should_resolve_resources:
                html_resolver: ResourceResolver | str = (
                    resource_resolver if resource_resolver is not None else "auto"
                )
                rendered_html = await resolve_html_resources(
                    rendered_html,
                    template_base=render_request.template.template_path,
                    strict=resource_strict,
                    resolver=html_resolver,
                    lease_id=lease_id,
                )

            return await render_html(
                HtmlRenderRequest(
                    content=ContentConfig(html=rendered_html),
                    render=render_request.render,
                ),
                session=session,
            )
        finally:
            if lease_id is not None:
                await release_filehost_lease(lease_id)


async def capture_html_element(
    url: str,
    element: str,
    page_kwargs: PageContextKwargs | None = None,
    goto_kwargs: GotoKwargs | None = None,
    screenshot_kwargs: LocatorScreenshotKwargs | None = None,
    *,
    session: SupportsBrowserSession | None = None,
) -> bytes:
    """捕获指定 URL 页面中的 HTML 元素截图。

    Args:
        url: 目标页面 URL。
        element: CSS 选择器，指定要捕获的元素。
        page_kwargs: 页面上下文配置。
        goto_kwargs: 页面导航配置。
        screenshot_kwargs: 元素截图配置。
        session: 浏览器会话。

    Returns:
        捕获的元素图片字节数据。
    """
    async with track_render(
        "playwright.html_render.capture_html_element",
        backend=RenderBackend.PLAYWRIGHT,
    ):
        page_options = page_kwargs or EMPTY_PAGE_CONTEXT_KWARGS
        goto_options = goto_kwargs or EMPTY_GOTO_KWARGS
        screenshot_options = screenshot_kwargs or EMPTY_LOCATOR_SCREENSHOT_KWARGS

        async with open_page_context(session=session, **page_options) as page:
            page.on(
                "console",
                lambda msg: logger.opt(colors=True).debug(
                    f"<cyan>[Browser Console]</cyan> {msg.text}"
                ),
            )
            await page.goto(url, **goto_options)
            await log_page_telemetry(
                page, op="playwright.html_render.capture_html_element"
            )
            return await page.locator(element).screenshot(**screenshot_options)


__all__ = [
    "capture_html_element",
    "read_file",
    "read_tpl",
    "register_render_context_provider",
    "render_html",
    "render_markdown",
    "render_template",
    "render_template_html",
    "render_text",
]
