from typing import Any, Literal

from nonebot.compat import ConfigDict, field_validator
from pydantic import BaseModel, Field


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
        v = v.strip()
        if not v:
            raise ValueError("template_path cannot be empty")
        return v

    @field_validator("template_name")
    @classmethod
    def validate_template_name(cls, v: str) -> str:
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


# Convenience creation functions
def create_png_config(
    quality_optimized: bool = False,
    viewport_width: int = 800,
    viewport_height: int = 600,
) -> RenderConfig:
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
    return RenderConfig(
        page=PageConfig(
            viewport=ViewportConfig(width=viewport_width, height=viewport_height)
        ),
        screenshot=JpegScreenshotOptions(quality=quality),
    )
