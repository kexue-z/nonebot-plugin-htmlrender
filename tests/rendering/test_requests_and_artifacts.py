from __future__ import annotations

from dataclasses import replace
import math
from typing import get_type_hints

import pytest

from nonebot_plugin_htmlrender.preparation import PreparedHtml, RasterOptions
from nonebot_plugin_htmlrender.raster import RasterImageFormat
from nonebot_plugin_htmlrender.rendering import (
    InvalidRenderRequest,
    PreparedHtmlExecutor,
    RenderedHtml,
    RenderedImage,
    RenderHtmlRequest,
    RenderMarkdownRequest,
    RenderTemplateRequest,
    ResourcePolicy,
)
from nonebot_plugin_htmlrender.rendering.requests import (
    POLICY_RESOLVE_MODES,
    resolve_mode_for_policy,
)
from nonebot_plugin_htmlrender.resources.config import ResourceResolveMode
from tests.image_fixtures import encoded_image


def test_rendered_image_exposes_bytes_and_media_type() -> None:
    data = encoded_image("png", width=800, height=600)
    image = RenderedImage.from_bytes(data, expected_format="png")

    assert bytes(image) == data
    assert image.media_type == "image/png"
    assert image.format == "png"
    assert image.width == 800
    assert image.height == 600


def test_public_raster_annotations_resolve_at_runtime() -> None:
    assert get_type_hints(RasterOptions)["format"] == RasterImageFormat
    assert get_type_hints(RenderedImage)["format"] == RasterImageFormat


def test_public_executor_annotations_resolve_at_runtime() -> None:
    annotations = get_type_hints(PreparedHtmlExecutor.execute)

    assert annotations == {
        "prepared": PreparedHtml,
        "options": RasterOptions,
        "resource_policy": ResourcePolicy | None,
        "timeout_seconds": float | None,
        "return": RenderedImage,
    }


def test_dataclass_replace_reinspects_encoded_metadata() -> None:
    original = RenderedImage.from_bytes(encoded_image("png", width=11, height=7))
    replacement_data = encoded_image("jpeg", width=19, height=13)

    replacement = replace(original, data=replacement_data)

    assert replace(original) == original
    assert replacement.data == replacement_data
    assert replacement.format == "jpeg"
    assert (replacement.width, replacement.height) == (19, 13)


def test_rendered_image_parses_jpeg_metadata() -> None:
    data = encoded_image("jpeg", width=37, height=29)

    image = RenderedImage.from_bytes(data)

    assert image.format == "jpeg"
    assert image.media_type == "image/jpeg"
    assert image.width == 37
    assert image.height == 29


def test_rendered_image_parses_progressive_jpeg_scans() -> None:
    data = encoded_image("jpeg", width=43, height=31, progressive=True)
    assert data.count(b"\xff\xda") > 1

    image = RenderedImage.from_bytes(data, expected_format="jpeg")

    assert (image.width, image.height) == (43, 31)


def test_rendered_image_accepts_jpeg_standalone_marker() -> None:
    data = encoded_image("jpeg", width=17, height=13)
    with_tem_marker = data[:2] + b"\xff\x01" + data[2:]

    image = RenderedImage.from_bytes(with_tem_marker)

    assert image.format == "jpeg"
    assert (image.width, image.height) == (17, 13)


@pytest.mark.parametrize(
    ("encoded_format", "expected_format"),
    [("png", "jpeg"), ("jpeg", "png")],
)
def test_rendered_image_rejects_format_mismatch(
    encoded_format: RasterImageFormat,
    expected_format: RasterImageFormat,
) -> None:
    with pytest.raises(ValueError, match="format mismatch"):
        RenderedImage.from_bytes(
            encoded_image(encoded_format),
            expected_format=expected_format,
        )


def test_rendered_image_rejects_corrupt_png_metadata() -> None:
    corrupted = bytearray(encoded_image("png"))
    corrupted[19] ^= 0x01

    with pytest.raises(ValueError, match="checksum"):
        RenderedImage.from_bytes(bytes(corrupted))


def test_rendered_image_rejects_truncated_jpeg_metadata() -> None:
    with pytest.raises(ValueError, match="JPEG"):
        RenderedImage.from_bytes(b"\xff\xd8\xff\xc0\x00")


def test_rendered_image_rejects_jpeg_scan_before_frame() -> None:
    scan_without_frame = b"\xff\xd8\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\xff\xd9"

    with pytest.raises(ValueError, match="scan appears before frame"):
        RenderedImage.from_bytes(scan_without_frame)


def test_rendered_html_stringifies_to_content() -> None:
    artifact = RenderedHtml(content="<p>hi</p>")

    assert str(artifact) == "<p>hi</p>"
    assert artifact.content == "<p>hi</p>"


def test_markdown_request_requires_content_or_path() -> None:
    with pytest.raises(InvalidRenderRequest, match="markdown"):
        RenderMarkdownRequest()


def test_template_request_requires_template_name() -> None:
    with pytest.raises(InvalidRenderRequest, match="template_name"):
        RenderTemplateRequest(template_path="templates", template_name="")


def test_template_request_snapshots_mutable_inputs() -> None:
    from types import MappingProxyType  # noqa: PLC0415

    live_variables: dict[str, object] = {"name": "a"}
    request = RenderTemplateRequest(
        template_path="templates",
        template_name="card.html",
        variables=live_variables,
        extensions=[],
    )

    # Mutating the caller's original dict must not affect the request.
    live_variables["name"] = "b"
    live_variables["injected"] = True
    assert dict(request.variables) == {"name": "a"}

    # The request owns a read-only snapshot, not the caller's live container.
    assert isinstance(request.variables, MappingProxyType)
    assert isinstance(request.extensions, tuple)


@pytest.mark.parametrize("timeout", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_timeout_must_be_finite_and_positive(timeout: float) -> None:
    with pytest.raises(InvalidRenderRequest, match="timeout_seconds"):
        RenderHtmlRequest(html="<p>hi</p>", timeout_seconds=timeout)


def test_policy_resolve_mode_mapping_is_exhaustive() -> None:
    assert set(POLICY_RESOLVE_MODES) == set(ResourcePolicy)
    for policy in ResourcePolicy:
        assert isinstance(resolve_mode_for_policy(policy), ResourceResolveMode)
