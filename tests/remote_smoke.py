from __future__ import annotations

import asyncio
import contextlib
from io import BytesIO
import os
from pathlib import Path
from urllib.parse import urlsplit

import nonebot
from PIL import Image, ImageChops, ImageStat
import uvicorn

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE_DIR = _PROJECT_ROOT / "tests" / "templates"
_IMAGE_FILE = _PROJECT_ROOT / "tests" / "resources" / "test_template_filter.png"
_RESOURCE_DIR = _IMAGE_FILE.parent
_ARTIFACT_IMAGE = (
    _PROJECT_ROOT / "tests" / ".artifacts" / "remote_filehost_rendered.png"
)


def _playwright_config() -> dict[str, object]:
    ws_endpoint = os.environ.get(
        "PLAYWRIGHT_WS_ENDPOINT", "ws://playwright:53333/playwright"
    )
    return {
        "engine": "chromium",
        "connect_ws": {"endpoint": ws_endpoint},
        "skip_browser_install": True,
        "resource_resolve_mode": "auto",
        "remote_local_resource_policy": "filehost",
        "local_local_resource_policy": "file",
        "filehost_allowed_paths": [str(_RESOURCE_DIR)],
    }


def _mean_abs_diff(rendered: Image.Image, expected: Image.Image) -> float:
    rendered_rgb = rendered.convert("RGB")
    expected_rgb = expected.convert("RGB")
    if rendered_rgb.size != expected_rgb.size:
        expected_rgb = expected_rgb.resize(rendered_rgb.size)

    diff = ImageChops.difference(rendered_rgb, expected_rgb)
    stat = ImageStat.Stat(diff)
    return sum(stat.mean) / len(stat.mean)


async def _main() -> None:
    nonebot.init(
        driver="~fastapi",
        host="0.0.0.0",  # noqa: S104
        port=9012,
        log_level="INFO",
        render_backend="playwright",
        render_startup_mode="probe",
        render_playwright=_playwright_config(),
    )

    nonebot.require("nonebot_plugin_htmlrender")

    from nonebot import get_asgi  # noqa: PLC0415

    from nonebot_plugin_htmlrender import (  # noqa: PLC0415
        render_html,
        render_template,
        resolve_template_vars,
        shutdown_render,
        startup_render,
    )

    server = uvicorn.Server(
        uvicorn.Config(
            app=get_asgi(),
            host="0.0.0.0",  # noqa: S104
            port=9012,
            log_level="info",
        )
    )
    server_task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.1)
    if not server.started:
        raise RuntimeError("Failed to start ASGI server for filehost route serving.")

    await startup_render()
    try:
        image_bytes = await render_html(
            "<html><body><h1>remote smoke</h1></body></html>",
            template_path="about:blank",
        )
        print(f"remote smoke html passed, image bytes: {len(image_bytes)}")  # noqa: T201

        resolved = await resolve_template_vars(
            {"avatar": _IMAGE_FILE},
            template_base=_TEMPLATE_DIR,
            strict=True,
            resolver="auto",
        )
        avatar_url = resolved["avatar"]
        if not isinstance(avatar_url, str) or not avatar_url.startswith(
            ("http://", "https://")
        ):
            raise RuntimeError(
                f"Expected filehost URL for remote resource, got: {avatar_url!r}"
            )
        avatar_parts = urlsplit(avatar_url)
        if not avatar_parts.scheme or not avatar_parts.netloc:
            raise RuntimeError(f"Invalid resolved filehost URL: {avatar_url!r}")
        base_url = f"{avatar_parts.scheme}://{avatar_parts.netloc}/"

        template_bytes = await render_template(
            str(_TEMPLATE_DIR),
            template_name="remote_filehost.html.jinja2",
            templates={
                "title": "remote filehost smoke",
                "avatar": avatar_url,
            },
            pages={
                "viewport": {"width": 1200, "height": 600},
                "base_url": base_url,
            },
            wait=3000,
            device_scale_factor=1,
            resolve_resources=False,
            resource_resolver=None,
            resource_strict=True,
        )
        _ARTIFACT_IMAGE.parent.mkdir(parents=True, exist_ok=True)
        _ARTIFACT_IMAGE.write_bytes(template_bytes)

        rendered = Image.open(BytesIO(template_bytes))
        expected = Image.open(_IMAGE_FILE)
        diff_score = _mean_abs_diff(rendered, expected)
        if diff_score > 8.0:
            raise RuntimeError(
                f"Rendered image differs too much from expected fixture: {diff_score:.2f}"
            )

        print(  # noqa: T201
            "remote smoke filehost passed, "
            f"resource_url={avatar_url}, image bytes: {len(template_bytes)}, "
            f"diff={diff_score:.2f}"
        )
    finally:
        await shutdown_render()
        server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(server_task, timeout=5)


if __name__ == "__main__":
    asyncio.run(_main())
