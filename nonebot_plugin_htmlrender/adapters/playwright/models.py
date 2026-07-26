from typing import ClassVar, Literal

from nonebot.compat import field_validator
from pydantic import BaseModel, ConfigDict, Field

from nonebot_plugin_htmlrender.rendering.errors import InvalidRenderRequest


class ViewportConfig(BaseModel):
    """Viewport configuration."""

    width: int = Field(default=800, ge=1, le=10000, description="Viewport width")
    height: int = Field(default=600, ge=1, le=10000, description="Viewport height")

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", validate_assignment=True
    )


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

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", validate_assignment=True
    )


class PngScreenshotOptions(ScreenshotOptions):
    """PNG screenshot configuration options.

    PNG format supports transparency, larger file size, suitable for
    transparent background scenarios.
    """

    format: Literal["png"] = Field(default="png", frozen=True)

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", validate_assignment=True
    )


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

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", validate_assignment=True
    )


ScreenshotConfig = PngScreenshotOptions | JpegScreenshotOptions


class PageConfig(BaseModel):
    """Page configuration options."""

    viewport: ViewportConfig = Field(
        default_factory=ViewportConfig, description="Viewport configuration"
    )

    document_url: str | None = Field(
        default=None,
        description="Optional URL to navigate before injecting HTML.",
    )

    user_agent: str | None = Field(
        default=None, description="User agent string, None for default"
    )

    extra_http_headers: dict[str, str] = Field(
        default_factory=dict, description="Additional HTTP headers"
    )

    @field_validator("document_url")
    @classmethod
    def validate_page_url(cls, v: str | None) -> str | None:
        """校验页面 URL 必须以受支持的协议前缀开头。

        Args:
            v: 待校验的 URL 字符串。

        Returns:
            去除前后空白后的合法 ``base_url``。

        Raises:
            ValueError: 当协议前缀不在允许列表中时抛出。
        """
        if v is None:
            return None
        v = v.strip()
        if not v.startswith(("file://", "http://", "https://", "about:")):
            raise ValueError(
                "page URL must start with 'file://', 'http://', 'https://', or 'about:'"
            )
        return v

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", validate_assignment=True
    )


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

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", validate_assignment=True
    )


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

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", validate_assignment=True
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

    if image_type == "png":
        return PngScreenshotOptions(
            device_scale_factor=device_scale_factor,
            timeout=screenshot_timeout if screenshot_timeout is not None else 30_000,
            full_page=full_page,
            wait_before_screenshot=wait_before_screenshot,
        )
    raise InvalidRenderRequest(f"Unsupported Playwright image format: {image_type!r}")
