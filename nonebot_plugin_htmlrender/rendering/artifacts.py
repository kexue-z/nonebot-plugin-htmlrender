"""Typed artifacts returned by the rendering application."""

from __future__ import annotations

from dataclasses import dataclass, field
import zlib

# Keep public annotations resolvable through typing.get_type_hints().
from nonebot_plugin_htmlrender.raster import RasterImageFormat  # noqa: TC001

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8"
_JPEG_START_OF_FRAME_MARKERS = frozenset(
    {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
)
_PNG_BIT_DEPTHS_BY_COLOR_TYPE: dict[int, frozenset[int]] = {
    0: frozenset({1, 2, 4, 8, 16}),
    2: frozenset({8, 16}),
    3: frozenset({1, 2, 4, 8}),
    4: frozenset({8, 16}),
    6: frozenset({8, 16}),
}


def _inspect_png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 33:
        raise ValueError("Cannot inspect PNG metadata: the IHDR chunk is truncated.")

    chunk_length = int.from_bytes(data[8:12], "big")
    chunk_type = data[12:16]
    if chunk_length != 13 or chunk_type != b"IHDR":
        raise ValueError(
            "Cannot inspect PNG metadata: IHDR must be the first 13-byte chunk."
        )

    chunk_data = data[16:29]
    expected_crc = int.from_bytes(data[29:33], "big")
    actual_crc = zlib.crc32(chunk_type + chunk_data)
    if expected_crc != actual_crc:
        raise ValueError("Cannot inspect PNG metadata: the IHDR checksum is invalid.")

    width = int.from_bytes(chunk_data[0:4], "big")
    height = int.from_bytes(chunk_data[4:8], "big")
    if width == 0 or height == 0:
        raise ValueError("Cannot inspect PNG metadata: dimensions must be positive.")

    bit_depth = chunk_data[8]
    color_type = chunk_data[9]
    valid_bit_depths = _PNG_BIT_DEPTHS_BY_COLOR_TYPE.get(color_type)
    if valid_bit_depths is None or bit_depth not in valid_bit_depths:
        raise ValueError(
            "Cannot inspect PNG metadata: unsupported color type or bit depth."
        )
    if chunk_data[10] != 0 or chunk_data[11] != 0 or chunk_data[12] not in {0, 1}:
        raise ValueError("Cannot inspect PNG metadata: unsupported encoding methods.")
    return width, height


def _inspect_jpeg_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 4:
        raise ValueError("Cannot inspect JPEG metadata: marker stream is truncated.")

    offset = len(_JPEG_SIGNATURE)
    while offset < len(data):
        if data[offset] != 0xFF:
            raise ValueError("Cannot inspect JPEG metadata: expected a marker prefix.")
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break

        marker = data[offset]
        offset += 1
        if marker == 0x00:
            raise ValueError(
                "Cannot inspect JPEG metadata: unexpected stuffed marker byte."
            )
        if marker == 0x01:
            continue
        if marker == 0xDA:
            raise ValueError(
                "Cannot inspect JPEG metadata: scan appears before frame dimensions."
            )
        if marker == 0xD9:
            raise ValueError(
                "Cannot inspect JPEG metadata: image ends before frame dimensions."
            )
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7:
            raise ValueError("Cannot inspect JPEG metadata: unexpected marker.")
        if offset + 2 > len(data):
            raise ValueError(
                "Cannot inspect JPEG metadata: segment length is truncated."
            )

        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2:
            raise ValueError("Cannot inspect JPEG metadata: invalid segment length.")
        segment_end = offset + segment_length
        if segment_end > len(data):
            raise ValueError(
                "Cannot inspect JPEG metadata: segment payload is truncated."
            )

        if marker in _JPEG_START_OF_FRAME_MARKERS:
            if segment_length < 11:
                raise ValueError(
                    "Cannot inspect JPEG metadata: frame segment is truncated."
                )
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            component_count = data[offset + 7]
            if segment_length != 8 + 3 * component_count:
                raise ValueError(
                    "Cannot inspect JPEG metadata: frame components are inconsistent."
                )
            if width == 0 or height == 0:
                raise ValueError(
                    "Cannot inspect JPEG metadata: frame dimensions must be positive."
                )
            return width, height

        offset = segment_end

    raise ValueError("Cannot inspect JPEG metadata: no frame dimensions were found.")


def _encoded_raster_metadata(
    data: bytes,
    expected_format: RasterImageFormat | None,
) -> tuple[RasterImageFormat, int, int]:
    if data.startswith(_PNG_SIGNATURE):
        image_format: RasterImageFormat = "png"
    elif data.startswith(_JPEG_SIGNATURE):
        image_format = "jpeg"
    else:
        raise ValueError("Encoded raster must have a PNG or JPEG signature.")

    if expected_format is not None and image_format != expected_format:
        raise ValueError(
            "Raster format mismatch: "
            f"expected {expected_format.upper()}, encoded {image_format.upper()}."
        )
    dimensions = (
        _inspect_png_dimensions(data)
        if image_format == "png"
        else _inspect_jpeg_dimensions(data)
    )
    return image_format, *dimensions


@dataclass(frozen=True, slots=True, init=False)
class RenderedImage:
    """PNG or JPEG output with metadata derived from its encoded bytes.

    The bounded inspection reads only the container metadata needed for format
    and dimensions; full pixel decoding remains the renderer's responsibility.
    """

    data: bytes
    format: RasterImageFormat = field(init=False)
    width: int = field(init=False)
    height: int = field(init=False)

    def __init__(
        self,
        data: bytes,
        *,
        expected_format: RasterImageFormat | None = None,
    ) -> None:
        if not isinstance(data, bytes):
            raise TypeError("RenderedImage data must be bytes.")
        image_format, width, height = _encoded_raster_metadata(
            data,
            expected_format,
        )
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "format", image_format)
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "height", height)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        expected_format: RasterImageFormat | None = None,
    ) -> RenderedImage:
        """Build an artifact after bounded inspection of encoded metadata."""
        return cls(data, expected_format=expected_format)

    @property
    def media_type(self) -> str:
        return f"image/{self.format}"

    def __bytes__(self) -> bytes:
        return self.data


@dataclass(frozen=True, slots=True)
class RenderedHtml:
    """HTML output of a template-to-html render operation."""

    content: str

    def __str__(self) -> str:
        return self.content


__all__ = ["RenderedHtml", "RenderedImage"]
