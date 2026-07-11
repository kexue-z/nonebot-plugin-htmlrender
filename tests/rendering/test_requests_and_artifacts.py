from __future__ import annotations

import pytest

from nonebot_plugin_htmlrender.rendering import (
    CapabilityUnavailable,
    InvalidRenderRequest,
    ProviderExecutionError,
    ProviderLifecycleError,
    ProviderNotConfigured,
    ProviderNotFound,
    ProviderUnavailable,
    RenderedHtml,
    RenderedImage,
    RenderHtmlRequest,
    RenderingError,
    RenderMarkdownRequest,
    RenderTemplateRequest,
    ResourceAccessDenied,
    ResourceNotFound,
    ResourceResolutionError,
    ResourceSizeExceeded,
    UnsupportedRequirement,
)


def test_rendered_image_exposes_bytes_and_media_type() -> None:
    image = RenderedImage(data=b"png-bytes", format="png", width=800, height=600)

    assert bytes(image) == b"png-bytes"
    assert image.media_type == "image/png"
    assert image.width == 800
    assert image.height == 600


def test_rendered_image_media_type_overrides() -> None:
    assert RenderedImage(data=b"", format="jpeg").media_type == "image/jpeg"
    assert RenderedImage(data=b"", format="svg").media_type == "image/svg+xml"


def test_rendered_html_stringifies_to_content() -> None:
    artifact = RenderedHtml(content="<p>hi</p>")

    assert str(artifact) == "<p>hi</p>"
    assert artifact.content == "<p>hi</p>"


def test_error_taxonomy_roots_at_rendering_error() -> None:
    for error_type in (
        InvalidRenderRequest,
        CapabilityUnavailable,
        UnsupportedRequirement,
        ProviderNotConfigured,
        ProviderNotFound,
        ProviderUnavailable,
        ProviderExecutionError,
        ProviderLifecycleError,
        ResourceResolutionError,
    ):
        assert issubclass(error_type, RenderingError)
    for error_type in (ResourceAccessDenied, ResourceNotFound, ResourceSizeExceeded):
        assert issubclass(error_type, ResourceResolutionError)


def test_markdown_request_requires_content_or_path() -> None:
    with pytest.raises(InvalidRenderRequest, match="markdown"):
        RenderMarkdownRequest()


def test_template_request_requires_template_name() -> None:
    with pytest.raises(InvalidRenderRequest, match="template_name"):
        RenderTemplateRequest(template_path="templates", template_name="")


def test_timeout_must_be_positive() -> None:
    with pytest.raises(InvalidRenderRequest, match="timeout_seconds"):
        RenderHtmlRequest(html="<p>hi</p>", timeout_seconds=0)
