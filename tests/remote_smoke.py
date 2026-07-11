from __future__ import annotations

import asyncio
from base64 import b64decode
from io import BytesIO
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory

import nonebot
from PIL import Image, ImageChops, ImageStat

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE_DIR = _PROJECT_ROOT / "tests" / "templates"
_IMAGE_FILE = _PROJECT_ROOT / "tests" / "resources" / "test_template_filter.png"
_KATEX_FONT_CSS = (
    _PROJECT_ROOT
    / "nonebot_plugin_htmlrender"
    / "templates"
    / "markdown"
    / "katex"
    / "katex.min.b64_fonts.css"
)
_ARTIFACT_DIR = _PROJECT_ROOT / "tests" / ".artifacts"
_FONT_DATA_RE = re.compile(r"data:font/woff2;base64,([^\")]+)")


def _playwright_config() -> dict[str, object]:
    ws_endpoint = os.environ.get(
        "PLAYWRIGHT_WS_ENDPOINT", "ws://playwright:53333/playwright"
    )
    return {
        "engine": "chromium",
        "connect_ws": {"endpoint": ws_endpoint},
        "skip_browser_install": True,
    }


def _mean_abs_diff(rendered: Image.Image, expected: Image.Image) -> float:
    rendered_rgb = rendered.convert("RGB")
    expected_rgb = expected.convert("RGB")
    if rendered_rgb.size != expected_rgb.size:
        expected_rgb = expected_rgb.resize(rendered_rgb.size)

    diff = ImageChops.difference(rendered_rgb, expected_rgb)
    stat = ImageStat.Stat(diff)
    return sum(stat.mean) / len(stat.mean)


def _assert_png(payload: bytes, *, label: str) -> Image.Image:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"{label} did not produce PNG output")
    image = Image.open(BytesIO(payload))
    image.load()
    if image.width <= 0 or image.height <= 0:
        raise RuntimeError(f"{label} produced an empty image")
    return image


def _prepare_local_fixtures(root: Path) -> tuple[Path, Path]:
    relative_image = root / "relative.png"
    background_image = root / "background.png"
    shutil.copyfile(_IMAGE_FILE, relative_image)
    shutil.copyfile(_IMAGE_FILE, background_image)
    shutil.copyfile(
        _TEMPLATE_DIR / "remote_filehost.html.jinja2",
        root / "remote_filehost.html.jinja2",
    )

    font_match = _FONT_DATA_RE.search(_KATEX_FONT_CSS.read_text(encoding="utf-8"))
    if font_match is None:
        raise RuntimeError("Could not locate an embedded WOFF2 fixture")
    (root / "smoke.woff2").write_bytes(b64decode(font_match.group(1)))

    markdown = root / "document.md"
    markdown.write_text(
        "![remote relative image](relative.png)",
        encoding="utf-8",
    )
    stylesheet = root / "text.css"
    stylesheet.write_text(
        """
        @font-face {
            font-family: "RemoteSmoke";
            src: url("smoke.woff2") format("woff2");
        }
        html, body {
            margin: 0;
            min-height: 600px;
        }
        .main-box {
            box-sizing: border-box;
            min-height: 600px;
            padding: 32px;
            color: white;
            background: #111 url("background.png") center / cover no-repeat;
            font-family: "RemoteSmoke", sans-serif;
        }
        """,
        encoding="utf-8",
    )
    return markdown, stylesheet


async def _main() -> None:
    nonebot.init(
        driver="~none",
        log_level="INFO",
        render_backend="playwright",
        render_startup_mode="off",
        render_playwright=_playwright_config(),
    )
    nonebot.require("nonebot_plugin_htmlrender")

    from nonebot_plugin_htmlrender import (  # noqa: PLC0415
        render_html,
        render_markdown,
        render_template,
        render_text,
        shutdown_render,
        startup_render,
    )

    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    await startup_render()
    try:
        html_bytes = await render_html(
            "<html><body><h1>remote smoke</h1></body></html>",
            device_scale_factor=1,
        )
        _assert_png(html_bytes, label="plain HTML")

        with TemporaryDirectory(prefix="htmlrender-memory-smoke-") as temporary:
            markdown_path, stylesheet_path = _prepare_local_fixtures(Path(temporary))

            text_bytes = await render_text(
                "remote font and background smoke",
                css_path=str(stylesheet_path),
                width=1200,
                device_scale_factor=1,
            )
            _assert_png(text_bytes, label="text CSS assets")
            (_ARTIFACT_DIR / "remote_memory_text.png").write_bytes(text_bytes)

            markdown_bytes = await render_markdown(
                md_path=str(markdown_path),
                width=1200,
                device_scale_factor=1,
            )
            _assert_png(markdown_bytes, label="Markdown relative image")
            (_ARTIFACT_DIR / "remote_memory_markdown.png").write_bytes(markdown_bytes)

            template_bytes = await render_template(
                temporary,
                template_name="remote_filehost.html.jinja2",
                templates={
                    "title": "remote template resource smoke",
                    "avatar": "relative.png",
                },
                pages={"viewport": {"width": 1200, "height": 600}},
                wait=100,
                device_scale_factor=1,
                resource_strict=True,
            )
        (_ARTIFACT_DIR / "remote_memory_template.png").write_bytes(template_bytes)

        rendered = _assert_png(template_bytes, label="template relative image")
        expected = Image.open(_IMAGE_FILE)
        diff_score = _mean_abs_diff(rendered, expected)
        if diff_score > 8.0:
            raise RuntimeError(
                f"Rendered template differs too much from fixture: {diff_score:.2f}"
            )

        print(  # noqa: T201
            "remote MEMORY smoke passed: "
            f"html={len(html_bytes)}, text={len(text_bytes)}, "
            f"markdown={len(markdown_bytes)}, template={len(template_bytes)}, "
            f"template_diff={diff_score:.2f}"
        )
    finally:
        await shutdown_render()


if __name__ == "__main__":
    asyncio.run(_main())
