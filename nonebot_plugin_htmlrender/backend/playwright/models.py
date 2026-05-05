from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from nonebot.compat import field_validator
from pydantic import BaseModel, ConfigDict, Field

from .types import PageContextKwargs, TemplatePageKwargs

if TYPE_CHECKING:
    from .types import ViewportSize


class ViewportConfig(BaseModel):
    """Viewport configuration."""

    width: int = Field(default=800, ge=1, le=10000, description="Viewport width")
    height: int = Field(default=600, ge=1, le=10000, description="Viewport height")

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ScreenshotOptions(BaseModel):
    """Base screenshot configuration options."""

    device_scale_factor: float = Field(
        default=2.0,
        ge=0.1,
        le=5.0,
        description="Device pixel ratio, controls image sharpness",
    )

    timeout: float = Field(
        default=30_000,
        ge=1000,
        description="Screenshot timeout (milliseconds)",
    )

    full_page: bool = Field(
        default=True,
        description="Whether to capture the entire page",
    )

    wait_before_screenshot: int = Field(
        default=0,
        ge=0,
        description="Wait time before screenshot (milliseconds)",
    )

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PngScreenshotOptions(ScreenshotOptions):
    """PNG screenshot configuration options.

    PNG format supports transparency, larger file size, suitable for
    transparent background scenarios.
    """

    format: Literal["png"] = Field(default="png", frozen=True)

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class JpegScreenshotOptions(ScreenshotOptions):
    """JPEG screenshot configuration options.

    JPEG format has high compression ratio, smaller file size, suitable for
    non-transparent background scenarios.
    """

    format: Literal["jpeg"] = Field(default="jpeg", frozen=True)
    quality: int = Field(
        default=80,
        ge=0,
        le=100,
        description="Image quality, range 0-100",
    )

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


ScreenshotConfig = PngScreenshotOptions | JpegScreenshotOptions


class PageConfig(BaseModel):
    """Page configuration options."""

    viewport: ViewportConfig = Field(
        default_factory=ViewportConfig, description="Viewport configuration"
    )

    base_url: str = Field(default="about:blank", description="Page base URL")

    user_agent: str | None = Field(
        default=None, description="User agent string, None for default"
    )

    extra_http_headers: dict[str, str] = Field(
        default_factory=dict, description="Additional HTTP headers"
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """校验 ``base_url`` 必须以受支持的协议前缀开头。

        Args:
            v: 待校验的 ``base_url`` 字符串。

        Returns:
            去除前后空白后的合法 ``base_url``。

        Raises:
            ValueError: 当协议前缀不在允许列表中时抛出。
        """
        v = v.strip()
        if not v.startswith(("file://", "http://", "https://", "about:")):
            raise ValueError(
                "base_url must start with 'file://', 'http://', 'https://', or 'about:'"
            )
        return v

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ContentConfig(BaseModel):
    """Content configuration options."""

    html: str = Field(description="HTML content")

    wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = Field(
        default="networkidle", description="Page load wait strategy"
    )

    additional_wait: int = Field(
        default=0,
        ge=0,
        description="Additional wait time (milliseconds)",
    )

    @field_validator("html")
    @classmethod
    def validate_html(cls, v: str) -> str:
        """校验 HTML 内容非空。

        Args:
            v: 待校验的 HTML 字符串。

        Returns:
            去除前后空白后的 HTML 内容。

        Raises:
            ValueError: 当内容为空字符串时抛出。
        """
        v = v.strip()
        if not v:
            raise ValueError("HTML content cannot be empty")
        return v

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TemplateConfig(BaseModel):
    """Template configuration."""

    template_path: str = Field(description="Template folder path")
    template_name: str = Field(description="Template file name")
    template_vars: dict[str, Any] = Field(
        default_factory=dict,
        description="Template variables",
    )
    custom_filters: dict[str, Any] = Field(
        default_factory=dict, description="Custom Jinja2 filters"
    )

    @field_validator("template_path")
    @classmethod
    def validate_template_path(cls, v: str) -> str:
        """校验模板目录路径非空。

        Args:
            v: 待校验的模板目录路径。

        Returns:
            去除前后空白后的合法路径字符串。

        Raises:
            ValueError: 当路径为空字符串时抛出。
        """
        v = v.strip()
        if not v:
            raise ValueError("template_path cannot be empty")
        return v

    @field_validator("template_name")
    @classmethod
    def validate_template_name(cls, v: str) -> str:
        """校验模板文件名非空。

        Args:
            v: 待校验的模板文件名。

        Returns:
            去除前后空白后的合法模板文件名。

        Raises:
            ValueError: 当文件名为空字符串时抛出。
        """
        v = v.strip()
        if not v:
            raise ValueError("template_name cannot be empty")
        return v

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RenderConfig(BaseModel):
    """Complete rendering configuration."""

    page: PageConfig = Field(
        default_factory=PageConfig,
        description="Page configuration",
    )
    screenshot: ScreenshotConfig = Field(
        default_factory=PngScreenshotOptions,
        description="Screenshot configuration",
        discriminator="format",
    )

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class HtmlRenderRequest(BaseModel):
    """HTML rendering request."""

    content: ContentConfig = Field(description="Content configuration")
    render: RenderConfig = Field(
        default_factory=RenderConfig,
        description="Render configuration",
    )

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TemplateRenderRequest(BaseModel):
    """Template rendering request."""

    template: TemplateConfig = Field(description="Template configuration")
    render: RenderConfig = Field(
        default_factory=RenderConfig, description="Render configuration"
    )

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def create_png_config(
    *,
    quality_optimized: bool = False,
    viewport_width: int = 800,
    viewport_height: int = 600,
) -> RenderConfig:
    """创建 PNG 格式的渲染配置。

    Args:
        quality_optimized: 为 True 时使用更高的设备像素比。
        viewport_width: 视口宽度（像素）。
        viewport_height: 视口高度（像素）。

    Returns:
        配置了 PNG 截图选项的 RenderConfig。
    """
    return RenderConfig(
        page=PageConfig(
            viewport=ViewportConfig(width=viewport_width, height=viewport_height)
        ),
        screenshot=PngScreenshotOptions(
            device_scale_factor=3.0 if quality_optimized else 2.0
        ),
    )


def create_jpeg_config(
    quality: int = 80,
    viewport_width: int = 800,
    viewport_height: int = 600,
) -> RenderConfig:
    """创建 JPEG 格式的渲染配置。

    Args:
        quality: 图片质量（0-100）。
        viewport_width: 视口宽度（像素）。
        viewport_height: 视口高度（像素）。

    Returns:
        配置了 JPEG 截图选项的 RenderConfig。
    """
    return RenderConfig(
        page=PageConfig(
            viewport=ViewportConfig(width=viewport_width, height=viewport_height)
        ),
        screenshot=JpegScreenshotOptions(quality=quality),
    )


def _build_screenshot_config(
    image_type: Literal["jpeg", "png"],
    *,
    quality: int | None,
    device_scale_factor: float,
    screenshot_timeout: float | None,
    full_page: bool,
    wait_before_screenshot: int,
) -> PngScreenshotOptions | JpegScreenshotOptions:
    """根据图片类型构建截图配置对象。"""
    if image_type == "jpeg":
        return JpegScreenshotOptions(
            quality=quality if quality is not None else 80,
            device_scale_factor=device_scale_factor,
            timeout=screenshot_timeout if screenshot_timeout is not None else 30_000,
            full_page=full_page,
            wait_before_screenshot=wait_before_screenshot,
        )

    return PngScreenshotOptions(
        device_scale_factor=device_scale_factor,
        timeout=screenshot_timeout if screenshot_timeout is not None else 30_000,
        full_page=full_page,
        wait_before_screenshot=wait_before_screenshot,
    )


def _page_context_kwargs(render: RenderConfig) -> PageContextKwargs:
    """从 RenderConfig 提取页面上下文参数。"""
    kwargs: PageContextKwargs = {
        "viewport": cast("ViewportSize", render.page.viewport.model_dump()),
        "device_scale_factor": render.screenshot.device_scale_factor,
    }
    if render.page.user_agent is not None:
        kwargs["user_agent"] = render.page.user_agent
    if render.page.extra_http_headers:
        kwargs["extra_http_headers"] = render.page.extra_http_headers
    return kwargs


def _build_html_render_request(
    html: str,
    *,
    template_path: str | None,
    image_type: Literal["jpeg", "png"],
    quality: int | None,
    device_scale_factor: float,
    screenshot_timeout: float | None,
    full_page: bool,
    wait: int,
    viewport: dict[str, int] | None = None,
    user_agent: str | None = None,
    extra_http_headers: dict[str, str] | None = None,
) -> HtmlRenderRequest:
    """从散列参数构建 HtmlRenderRequest。"""
    page = PageConfig(
        viewport=ViewportConfig(**(viewport or {"width": 800, "height": 600})),
        base_url=template_path or "about:blank",
        user_agent=user_agent,
        extra_http_headers=extra_http_headers or {},
    )
    screenshot = _build_screenshot_config(
        image_type,
        quality=quality,
        device_scale_factor=device_scale_factor,
        screenshot_timeout=screenshot_timeout,
        full_page=full_page,
        wait_before_screenshot=wait,
    )
    return HtmlRenderRequest(
        content=ContentConfig(
            html=html,
            additional_wait=wait,
        ),
        render=RenderConfig(page=page, screenshot=screenshot),
    )


def _build_template_render_request(
    template_path: str,
    template_name: str,
    *,
    template_vars: dict[str, Any],
    custom_filters: dict[str, Any] | None,
    pages: TemplatePageKwargs | None,
    image_type: Literal["jpeg", "png"],
    quality: int | None,
    device_scale_factor: float,
    screenshot_timeout: float | None,
    wait: int,
) -> TemplateRenderRequest:
    """从散列参数构建 TemplateRenderRequest。"""
    page_kwargs = dict(pages or {})
    viewport = cast(
        "ViewportSize",
        page_kwargs.pop("viewport", {"width": 500, "height": 10}),
    )
    base_url = cast("str", page_kwargs.pop("base_url", f"file://{Path.cwd()}"))
    user_agent = cast("str | None", page_kwargs.pop("user_agent", None))
    extra_http_headers = cast(
        "dict[str, str]",
        page_kwargs.pop("extra_http_headers", {}),
    )

    return TemplateRenderRequest(
        template=TemplateConfig(
            template_path=template_path,
            template_name=template_name,
            template_vars=template_vars,
            custom_filters=custom_filters or {},
        ),
        render=RenderConfig(
            page=PageConfig(
                viewport=ViewportConfig(**viewport),
                base_url=base_url,
                user_agent=user_agent,
                extra_http_headers=extra_http_headers,
            ),
            screenshot=_build_screenshot_config(
                image_type,
                quality=quality,
                device_scale_factor=device_scale_factor,
                screenshot_timeout=screenshot_timeout,
                full_page=True,
                wait_before_screenshot=wait,
            ),
        ),
    )
