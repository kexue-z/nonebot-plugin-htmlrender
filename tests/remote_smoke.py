from __future__ import annotations

import asyncio
from base64 import b64decode
from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import urlopen

from fastapi import FastAPI, Request
import nonebot
from nonebot.drivers import ASGIMixin
from PIL import Image, ImageChops, ImageStat
from uvicorn import Config as UvicornConfig
from uvicorn import Server as UvicornServer

if TYPE_CHECKING:
    from collections.abc import Iterable

    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.responses import Response

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
_MARKDOWN_SENTINEL = (17, 199, 83)
_FILEHOST_BIND_HOST = "0.0.0.0"  # noqa: S104 - cross-container smoke server
_FILEHOST_BIND_PORT = int(os.environ.get("FILEHOST_BIND_PORT", "9012"))
_FILEHOST_PUBLIC_URL = os.environ.get(
    "FILEHOST_PUBLIC_URL",
    f"http://render:{_FILEHOST_BIND_PORT}/_htmlrender/assets/",
)
_FILEHOST_PUBLIC_PATH = f"{urlsplit(_FILEHOST_PUBLIC_URL).path.rstrip('/')}/"
_FILEHOST_REQUEST_HEADER = "X-HTMLRender-Filehost-Request"
_FILEHOST_REQUEST_TOKEN = "remote-smoke-filehost-token"


@dataclass(frozen=True, slots=True)
class _FilehostHit:
    path: str
    request_token: str | None
    status_code: int
    allow_origin: str | None


@dataclass(slots=True)
class _RunningServer:
    server: UvicornServer
    task: asyncio.Task[None]


def _remote_resource_policy() -> str:
    policy = os.environ.get("REMOTE_RESOURCE_POLICY", "memory").strip().lower()
    if policy not in {"filehost", "memory"}:
        raise RuntimeError(f"Unsupported remote resource policy: {policy!r}")
    return policy


def _playwright_config(policy: str) -> dict[str, object]:
    ws_endpoint = os.environ.get(
        "PLAYWRIGHT_WS_ENDPOINT", "ws://playwright:53333/playwright"
    )
    return {
        "engine": "chromium",
        "connect_ws": {"endpoint": ws_endpoint},
        "skip_browser_install": True,
        "remote_local_resource_policy": policy,
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


def _assert_color_coverage(
    image: Image.Image,
    *,
    label: str,
    expected: tuple[int, int, int],
    minimum_pixels: int,
    tolerance: int = 3,
) -> int:
    pixels = cast(
        "Iterable[tuple[int, int, int]]",
        image.convert("RGB").get_flattened_data(),
    )
    matching = sum(
        1
        for pixel in pixels
        if all(
            abs(actual - target) <= tolerance
            for actual, target in zip(pixel, expected, strict=True)
        )
    )
    if matching < minimum_pixels:
        raise RuntimeError(
            f"{label} did not load its sentinel asset: "
            f"expected at least {minimum_pixels} matching pixels, got {matching}"
        )
    return matching


def _prepare_local_fixtures(root: Path) -> tuple[Path, Path]:
    relative_image = root / "relative.png"
    background_image = root / "background.png"
    markdown_image = root / "markdown-relative.png"
    shutil.copyfile(_IMAGE_FILE, relative_image)
    shutil.copyfile(_IMAGE_FILE, background_image)
    Image.new("RGB", (320, 180), _MARKDOWN_SENTINEL).save(markdown_image)
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
        "![remote relative image](markdown-relative.png)",
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


def _install_filehost_probe() -> list[_FilehostHit]:
    driver = nonebot.get_driver()
    if not isinstance(driver, ASGIMixin) or not isinstance(driver.server_app, FastAPI):
        raise RuntimeError("filehost smoke requires the FastAPI driver")

    hits: list[_FilehostHit] = []

    @driver.server_app.middleware("http")
    async def _record_filehost_request(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith(_FILEHOST_PUBLIC_PATH):
            hits.append(
                _FilehostHit(
                    path=request.url.path,
                    request_token=request.headers.get(_FILEHOST_REQUEST_HEADER),
                    status_code=response.status_code,
                    allow_origin=response.headers.get("Access-Control-Allow-Origin"),
                )
            )
        return response

    return hits


async def _start_filehost_server() -> _RunningServer:
    driver = nonebot.get_driver()
    if not isinstance(driver, ASGIMixin):
        raise RuntimeError("filehost smoke requires an ASGI driver")

    server = UvicornServer(
        UvicornConfig(
            driver.server_app,
            host=_FILEHOST_BIND_HOST,
            port=_FILEHOST_BIND_PORT,
            log_level="info",
        )
    )
    task = asyncio.create_task(server.serve())
    for _ in range(600):
        if server.started:
            return _RunningServer(server=server, task=task)
        if task.done():
            await task
            raise RuntimeError("filehost server stopped before becoming ready")
        await asyncio.sleep(0.05)

    server.should_exit = True
    await task
    raise RuntimeError("Timed out waiting for the filehost server")


async def _stop_filehost_server(running: _RunningServer) -> None:
    running.server.should_exit = True
    await running.task


def _http_status(url: str) -> int:
    try:
        with urlopen(url, timeout=5) as response:  # noqa: S310 - local smoke server
            return response.status
    except HTTPError as error:
        return error.code


async def _assert_filehost_requests(hits: list[_FilehostHit]) -> None:
    if not hits:
        raise RuntimeError("Remote Chromium did not request any filehost assets")

    invalid = [
        hit
        for hit in hits
        if hit.request_token != _FILEHOST_REQUEST_TOKEN
        or hit.status_code != 200
        or hit.allow_origin != "*"
    ]
    if invalid:
        raise RuntimeError(f"Invalid authenticated filehost requests: {invalid!r}")

    suffixes = {Path(hit.path).suffix.lower() for hit in hits}
    missing = {".css", ".png", ".woff2"} - suffixes
    if missing:
        raise RuntimeError(
            f"Remote Chromium did not fetch required filehost asset types: {missing}"
        )

    status = await asyncio.to_thread(
        _http_status,
        f"http://127.0.0.1:{_FILEHOST_BIND_PORT}{hits[0].path}",
    )
    if status != 403:
        raise RuntimeError(
            f"Unauthenticated filehost request returned {status}, expected 403"
        )


async def _main() -> None:
    policy = _remote_resource_policy()
    with TemporaryDirectory(prefix=f"htmlrender-{policy}-smoke-") as temporary:
        fixture_root = Path(temporary)
        markdown_path, stylesheet_path = _prepare_local_fixtures(fixture_root)
        nonebot.init(
            driver="~fastapi" if policy == "filehost" else "~none",
            host=_FILEHOST_BIND_HOST,
            port=_FILEHOST_BIND_PORT,
            log_level="INFO",
            render={
                "provider": "playwright",
                "startup": "off",
                "provider_config": _playwright_config(policy),
                "resources": {
                    "local_access": {"allowed_paths": [str(fixture_root)]},
                    "filehost": {
                        "public_base_url": _FILEHOST_PUBLIC_URL,
                        "request_header_name": _FILEHOST_REQUEST_HEADER,
                        "request_header_value": _FILEHOST_REQUEST_TOKEN,
                    },
                },
            },
        )
        nonebot.require("nonebot_plugin_htmlrender")

        from nonebot_plugin_htmlrender import (  # noqa: PLC0415
            ResourcePolicy,
            get_default_application,
            render_html,
            render_markdown,
            render_template,
            render_text,
        )

        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        filehost_hits = _install_filehost_probe() if policy == "filehost" else []
        running_server = (
            await _start_filehost_server() if policy == "filehost" else None
        )
        application = get_default_application()
        try:
            await application.startup()
            html_artifact = await render_html(
                "<html><body><h1>remote smoke</h1></body></html>",
                device_pixel_ratio=1.0,
            )
            html_bytes = bytes(html_artifact)
            _assert_png(html_bytes, label="plain HTML")

            asset_graph_bytes = bytes(
                await render_html(
                    """
                    <html>
                      <head><link rel="stylesheet" href="text.css" /></head>
                      <body><div class="main-box">remote asset graph</div></body>
                    </html>
                    """,
                    base_url=f"{fixture_root.as_uri().rstrip('/')}/",
                    width=1200,
                    height=600,
                    device_pixel_ratio=1.0,
                    resource_policy=ResourcePolicy.STRICT,
                )
            )
            _assert_png(asset_graph_bytes, label="linked CSS asset graph")
            (_ARTIFACT_DIR / f"remote_{policy}_asset_graph.png").write_bytes(
                asset_graph_bytes
            )

            text_bytes = bytes(
                await render_text(
                    "remote font and background smoke",
                    css_path=str(stylesheet_path),
                    width=1200,
                    device_pixel_ratio=1.0,
                )
            )
            _assert_png(text_bytes, label="text CSS assets")
            (_ARTIFACT_DIR / f"remote_{policy}_text.png").write_bytes(text_bytes)

            markdown_bytes = bytes(
                await render_markdown(
                    markdown_path=str(markdown_path),
                    width=1200,
                    device_pixel_ratio=1.0,
                )
            )
            markdown_rendered = _assert_png(
                markdown_bytes,
                label="Markdown relative image",
            )
            markdown_pixels = _assert_color_coverage(
                markdown_rendered,
                label="Markdown relative image",
                expected=_MARKDOWN_SENTINEL,
                minimum_pixels=10_000,
            )
            (_ARTIFACT_DIR / f"remote_{policy}_markdown.png").write_bytes(
                markdown_bytes
            )

            template_bytes = bytes(
                await render_template(
                    fixture_root,
                    "remote_filehost.html.jinja2",
                    {
                        "title": "remote template resource smoke",
                        "avatar": "relative.png",
                    },
                    width=1200,
                    height=600,
                    device_pixel_ratio=1.0,
                    resource_policy=ResourcePolicy.STRICT,
                )
            )
            (_ARTIFACT_DIR / f"remote_{policy}_template.png").write_bytes(
                template_bytes
            )

            rendered = _assert_png(template_bytes, label="template relative image")
            expected = Image.open(_IMAGE_FILE)
            diff_score = _mean_abs_diff(rendered, expected)
            if diff_score > 8.0:
                raise RuntimeError(
                    f"Rendered template differs too much from fixture: {diff_score:.2f}"
                )

            if policy == "filehost":
                await _assert_filehost_requests(filehost_hits)

            print(  # noqa: T201
                f"remote {policy.upper()} smoke passed: "
                f"html={len(html_bytes)}, asset_graph={len(asset_graph_bytes)}, "
                f"text={len(text_bytes)}, "
                f"markdown={len(markdown_bytes)}, template={len(template_bytes)}, "
                f"markdown_pixels={markdown_pixels}, "
                f"template_diff={diff_score:.2f}, filehost_hits={len(filehost_hits)}"
            )
        finally:
            await application.aclose()
            if running_server is not None:
                await _stop_filehost_server(running_server)


if __name__ == "__main__":
    asyncio.run(_main())
