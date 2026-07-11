from contextlib import suppress
from html import unescape
from importlib import import_module
import mimetypes
from pathlib import Path
from typing import Any, Literal, cast
from typing_extensions import Unpack
from urllib.parse import urldefrag, urlsplit

from anyio import CancelScope
from nonebot.log import logger

from nonebot_plugin_htmlrender.backend.playwright.config import get_playwright_config
from nonebot_plugin_htmlrender.consts import (
    LocalLocalResourcePolicy,
    RemoteLocalResourcePolicy,
    RenderBackend,
    ResourceResolveMode,
)
from nonebot_plugin_htmlrender.preparation import (
    PreparedAsset,
    PreparedHtml,
    prepare_html,
    prepare_markdown,
    prepare_template,
    prepare_text,
)
from nonebot_plugin_htmlrender.preparation.assets import (
    PreparedAssetIndex,
    resolve_document_reference,
)
from nonebot_plugin_htmlrender.preparation.materialize import (
    AssetMaterializationError,
    materialize_local_assets,
)
from nonebot_plugin_htmlrender.preparation.references import (
    css_resource_references,
    inspect_html_references,
    rewrite_css_references,
)
from nonebot_plugin_htmlrender.preparation.resolve import resolve_html_resources
from nonebot_plugin_htmlrender.resources import (
    FileCachePolicy,
    PackageResourceSource,
    ResourceResolver,
    is_remote_playwright_mode,
    read_resource_text,
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
from .prepared import (
    BrowserLoadPlan,
    build_browser_load_plan,
    install_browser_asset_routes,
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
BUILTIN_TEMPLATES = PackageResourceSource(
    "nonebot_plugin_htmlrender",
    "templates",
)


def create_filehost_lease() -> str:
    filehost = import_module("nonebot_plugin_htmlrender.resources.filehost")
    create_lease = filehost.create_filehost_lease

    return create_lease()


async def release_filehost_lease(lease_id: str) -> None:
    filehost = import_module("nonebot_plugin_htmlrender.resources.filehost")
    release_lease = filehost.release_filehost_lease

    await release_lease(lease_id)


async def resolve_filehost_url(
    value: bytes,
    *,
    lease_id: str,
    suffix: str | None,
) -> str:
    filehost = import_module("nonebot_plugin_htmlrender.resources.filehost")
    filehost_url = filehost.filehost_url

    return await filehost_url(value, lease_id=lease_id, suffix=suffix)


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


def _is_remote_session(session: SupportsBrowserSession | None) -> bool:
    """Use the mode selected for this session, with config as legacy fallback."""
    mode = getattr(session, "mode", None)
    if mode is not None:
        mode_value = _enum_value(mode)
        if mode_value in {"remote_cdp", "remote_ws"}:
            return True
        if mode_value == "local_pw":
            return False
    return is_remote_playwright_mode()


def _document_url_for_render(
    render: RenderConfig,
) -> str | None:
    """Return only the explicit navigation URL; resource bases live elsewhere."""
    document_url = render.page.document_url
    if document_url in {None, "about:blank"}:
        return None
    return document_url


def _local_resource_policy(*, remote_mode: bool) -> str:
    config = get_playwright_config()
    policy = (
        getattr(
            config,
            "remote_local_resource_policy",
            RemoteLocalResourcePolicy.MEMORY,
        )
        if remote_mode
        else getattr(
            config,
            "local_local_resource_policy",
            LocalLocalResourcePolicy.FILE,
        )
    )
    return _enum_value(policy)


def _effective_resource_resolver(
    resolver: ResourceResolver | str | None,
    *,
    policy: str,
) -> ResourceResolver | str:
    """Bind automatic resolution to the policy selected for the actual session."""
    if resolver is None or (isinstance(resolver, str) and resolver == "auto"):
        return policy
    return resolver


def _prepared_references(
    prepared: PreparedHtml,
    *,
    fallback_base_url: str | None = None,
) -> list[tuple[str, str | None]]:
    root_base = prepared.base_url or fallback_base_url
    snapshot = inspect_html_references(
        prepared.html,
        base_url=root_base,
    )
    document_base_url = (
        resolve_document_reference(root_base, snapshot.base_href)
        if snapshot.base_href is not None
        else root_base
    )
    references = [(reference, document_base_url) for reference in snapshot.references]
    for stylesheet in prepared.stylesheets:
        if stylesheet.embedded:
            continue
        references.extend(
            (reference, stylesheet.base_url or document_base_url)
            for reference in css_resource_references(stylesheet.css)
        )
    return references


def _assert_no_local_resources(
    prepared: PreparedHtml,
    *,
    document_url: str | None,
) -> None:
    if document_url is not None and urlsplit(document_url).scheme == "file":
        raise AssetMaterializationError(
            "Local file document URLs are not allowed under the error resource policy."
        )
    fallback_base = (
        document_url
        if prepared.base_url is None
        and document_url is not None
        and urlsplit(document_url).scheme in {"http", "https"}
        else None
    )
    index = PreparedAssetIndex(
        prepared.assets,
        base_url=prepared.base_url or fallback_base,
    )
    for reference, base_url in _prepared_references(
        prepared,
        fallback_base_url=fallback_base,
    ):
        base_url = base_url or fallback_base
        if index.match(reference, base_url=base_url) is not None:
            continue
        canonical = resolve_document_reference(base_url, reference)
        parsed = urlsplit(canonical)
        if parsed.scheme == "file" or (
            not parsed.scheme and not canonical.startswith("#")
        ):
            raise AssetMaterializationError(
                f"Local resource {reference!r} is not allowed under the error "
                "resource policy."
            )


def _asset_media_type(asset: PreparedAsset) -> str:
    return asset.media_type or mimetypes.guess_type(asset.source)[0] or ""


def _asset_suffix(asset: PreparedAsset) -> str | None:
    media_type = _asset_media_type(asset)
    if media_type == "text/css":
        return ".css"
    if media_type and (guessed := mimetypes.guess_extension(media_type, strict=False)):
        return guessed
    source_suffix = Path(urlsplit(asset.source).path).suffix.lower()
    return source_suffix or None


async def _publish_prepared_assets(
    prepared: PreparedHtml,
    *,
    lease_id: str,
) -> dict[str, str]:
    """Publish an asset graph bottom-up, rewriting CSS children to hosted URLs."""
    index = PreparedAssetIndex(prepared.assets, base_url=prepared.base_url)
    published: dict[int, str] = {}
    visiting: set[int] = set()

    async def publish(asset: PreparedAsset) -> str:
        asset_id = id(asset)
        if (url := published.get(asset_id)) is not None:
            return url
        if asset_id in visiting:
            raise AssetMaterializationError(
                f"Cyclic prepared stylesheet dependency at {asset.source!r}"
            )
        visiting.add(asset_id)
        payload = asset.data
        if _asset_media_type(asset) == "text/css":
            try:
                css = payload.decode("utf-8-sig")
            except UnicodeDecodeError:
                pass
            else:
                child_urls: dict[int, str] = {}
                for reference in css_resource_references(css):
                    child = index.match(reference, base_url=asset.source)
                    if child is not None:
                        child_urls[id(child)] = await publish(child)

                def rewrite_child(reference: str) -> str | None:
                    child = index.match(reference, base_url=asset.source)
                    if child is None:
                        normalized = unescape(reference).strip()
                        resolved = resolve_document_reference(asset.source, normalized)
                        if not resolved or resolved == normalized:
                            return None
                        _, fragment = urldefrag(normalized)
                        return f"{resolved}#{fragment}" if fragment else resolved
                    if (child_url := child_urls.get(id(child))) is None:
                        return None
                    _, fragment = urldefrag(unescape(reference).strip())
                    return f"{child_url}#{fragment}" if fragment else child_url

                payload = rewrite_css_references(css, rewrite_child).encode("utf-8")
        url = await resolve_filehost_url(
            payload,
            lease_id=lease_id,
            suffix=_asset_suffix(asset),
        )
        published[asset_id] = url
        visiting.remove(asset_id)
        return url

    urls: dict[str, str] = {}
    for asset in prepared.assets:
        urls[asset.source] = await publish(asset)
    return urls


async def read_file(path: str) -> str:
    """异步读取文件内容。"""
    return await read_resource_text(path)


async def read_tpl(path: str) -> str:
    """读取模板目录下的文件内容。"""
    return await read_resource_text(
        BUILTIN_TEMPLATES.resource(path),
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


async def _execute_browser_load_plan(
    plan: BrowserLoadPlan,
    *,
    content: ContentConfig,
    render: RenderConfig,
    session: SupportsBrowserSession | None,
    page_kwargs: PageContextKwargs,
    telemetry_op: str,
) -> bytes:
    """Execute a fully resolved load plan in one Playwright page."""
    async with open_page_context(
        session=session,
        **cast(
            "PageContextKwargs",
            {**_page_context_kwargs(render), **page_kwargs},
        ),
    ) as page:
        remote_mode = _is_remote_session(session)
        if _local_resource_policy(remote_mode=remote_mode) == "filehost":
            await install_filehost_request_route(
                page,
                filehost_headers=get_filehost_request_headers(),
            )

        # Install the narrow route after the catch-all filehost route so it gets
        # first chance to fulfil immutable in-memory resources.
        await install_browser_asset_routes(page, plan)
        _setup_page_logging(page)
        if plan.document_url is not None:
            await page.goto(plan.document_url)
        await page.set_content(plan.html, wait_until=content.wait_until)
        await page.wait_for_timeout(content.additional_wait)
        await log_page_telemetry(page, op=telemetry_op)
        screenshot = render.screenshot
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


async def render_prepared_html(
    prepared: PreparedHtml,
    *,
    content: ContentConfig,
    render: RenderConfig,
    session: SupportsBrowserSession | None,
    page_kwargs: PageContextKwargs | None = None,
    strict_assets: bool | None = None,
    filehost_lease_id: str | None = None,
    telemetry_op: str = "playwright.html_render.render_html",
) -> bytes:
    """Apply local-resource policy and render a prepared document."""
    remote_mode = _is_remote_session(session)
    policy = _local_resource_policy(remote_mode=remote_mode)
    document_url = _document_url_for_render(render)
    fallback_base_url = (
        document_url
        if prepared.base_url is None
        and document_url is not None
        and urlsplit(document_url).scheme in {"http", "https"}
        else None
    )
    strict = remote_mode if strict_assets is None else strict_assets
    asset_urls: dict[str, str] | None = None
    owns_lease = False
    try:
        if policy == RemoteLocalResourcePolicy.MEMORY.value:
            prepared = await materialize_local_assets(
                prepared,
                strict=strict,
                fallback_base_url=fallback_base_url,
            )
        elif policy == RemoteLocalResourcePolicy.FILEHOST.value:
            prepared = await materialize_local_assets(
                prepared,
                strict=strict,
                fallback_base_url=fallback_base_url,
            )
            if prepared.assets:
                if filehost_lease_id is None:
                    filehost_lease_id = create_filehost_lease()
                    owns_lease = True
                asset_urls = await _publish_prepared_assets(
                    prepared,
                    lease_id=filehost_lease_id,
                )
        elif policy == RemoteLocalResourcePolicy.ERROR.value:
            _assert_no_local_resources(prepared, document_url=document_url)
        elif policy not in {
            RemoteLocalResourcePolicy.PASSTHROUGH.value,
            LocalLocalResourcePolicy.FILE.value,
        }:
            raise RuntimeError(f"Unsupported local resource policy: {policy!r}")

        plan = build_browser_load_plan(
            prepared,
            document_url=document_url,
            asset_urls=asset_urls,
            allow_file_base_href=(
                policy
                in {
                    RemoteLocalResourcePolicy.PASSTHROUGH.value,
                    LocalLocalResourcePolicy.FILE.value,
                }
            ),
        )
        return await _execute_browser_load_plan(
            plan,
            content=content,
            render=render,
            session=session,
            page_kwargs=page_kwargs or EMPTY_PAGE_CONTEXT_KWARGS,
            telemetry_op=telemetry_op,
        )
    finally:
        if owns_lease and filehost_lease_id is not None:
            with CancelScope(shield=True):
                await release_filehost_lease(filehost_lease_id)


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
        resource_base_url = None
    else:
        resource_base_url = template_path
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

    prepared = prepare_html(
        render_request.content.html,
        base_url=resource_base_url,
    )
    async with track_render(
        "playwright.html_render.render_html",
        backend=RenderBackend.PLAYWRIGHT,
    ):
        return await render_prepared_html(
            prepared,
            content=render_request.content,
            render=render_request.render,
            session=session,
            page_kwargs=cast("PageContextKwargs", kwargs),
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
        resource_strict: 无法解析本地资源时是否立即失败。
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

        render_config = render or RenderConfig(
            page=PageConfig(
                viewport=ViewportConfig(width=width, height=10),
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
        return await render_prepared_html(
            prepared,
            content=ContentConfig(html=prepared.html),
            render=render_config,
            session=session,
            strict_assets=True,
            telemetry_op="playwright.html_render.render_text",
        )


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
    resource_strict: bool = False,
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
            render = RenderConfig(
                page=PageConfig(
                    viewport=ViewportConfig(width=width, height=10),
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

        return await render_prepared_html(
            prepared,
            content=ContentConfig(html=prepared.html),
            render=render,
            session=session,
            strict_assets=resource_strict,
            telemetry_op="playwright.html_render.render_markdown",
        )


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

        remote_mode = _is_remote_session(session)
        local_resource_policy = _local_resource_policy(remote_mode=remote_mode)
        should_resolve_resources = resolve_resources
        if should_resolve_resources is None:
            should_resolve_resources = (
                get_playwright_config().resource_resolve_mode != ResourceResolveMode.OFF
            )

        effective_resolver = _effective_resource_resolver(
            resource_resolver,
            policy=local_resource_policy,
        )
        resolver_uses_filehost = (
            should_resolve_resources
            and isinstance(effective_resolver, str)
            and effective_resolver == RemoteLocalResourcePolicy.FILEHOST.value
        )
        render_uses_filehost = (
            local_resource_policy == RemoteLocalResourcePolicy.FILEHOST.value
        )

        if resolver_uses_filehost or render_uses_filehost:
            # Registration is prewarm/indexing metadata owned by the filehost adapter.
            with suppress(Exception):
                register_filehost_resource_root(render_request.template.template_path)

        lease_id = create_filehost_lease() if resolver_uses_filehost else None
        try:
            if should_resolve_resources:
                resolved_template_vars = await resolve_template_vars(
                    render_request.template.template_vars,
                    template_base=render_request.template.template_path,
                    strict=resource_strict,
                    resolver=effective_resolver,
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

            if remote_mode:
                check_remote_pna_context(
                    base_url=(render_request.render.page.document_url or "about:blank"),
                    template_vars=render_request.template.template_vars,
                    strict=resource_strict,
                )

            prepared = await prepare_template(
                render_request.template.template_path,
                render_request.template.template_name,
                render_request.template.template_vars,
                filters=render_request.template.custom_filters,
            )

            if should_resolve_resources:
                rendered_html = await resolve_html_resources(
                    prepared.html,
                    template_base=render_request.template.template_path,
                    strict=resource_strict,
                    resolver=effective_resolver,
                    lease_id=lease_id,
                )
                prepared = prepare_html(
                    rendered_html,
                    base_url=prepared.base_url,
                    assets=prepared.assets,
                )
            return await render_prepared_html(
                prepared,
                content=ContentConfig(html=prepared.html),
                render=render_request.render,
                session=session,
                strict_assets=resource_strict,
                filehost_lease_id=lease_id,
                telemetry_op="playwright.html_render.render_template",
            )
        finally:
            if lease_id is not None:
                with CancelScope(shield=True):
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
