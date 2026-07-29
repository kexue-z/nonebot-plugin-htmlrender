"""Payload-free diagnostics: untrusted page content must not reach logs."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.log import logger
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SECRET = "sentinel-Sup3rSecret-秘密-value"


@contextmanager
def _captured_logs() -> Iterator[list[str]]:
    records: list[str] = []
    handler_id = logger.add(records.append, level="DEBUG", format="{message}")
    try:
        yield records
    finally:
        logger.remove(handler_id)


@dataclass(frozen=True)
class _ConsoleStub:
    type: str
    text: str


@dataclass(frozen=True)
class _RequestStub:
    url: str
    method: str
    resource_type: str
    failure: str


@dataclass(frozen=True)
class _ResponseStub:
    url: str
    status: int
    request: _RequestStub


def test_page_logging_handlers_never_emit_console_or_error_payload() -> None:
    from nonebot_plugin_htmlrender.adapters.playwright._page import (  # noqa: PLC0415
        log_console_event,
        log_page_error_event,
        log_request_failed_event,
        log_response_event,
    )

    console = _ConsoleStub(type="error", text=_SECRET)
    request = _RequestStub(
        url=f"https://evil.test/{_SECRET}",
        method="GET",
        resource_type="image",
        failure=_SECRET,
    )
    response = _ResponseStub(
        url=f"https://evil.test/{_SECRET}", status=500, request=request
    )

    with _captured_logs() as records:
        log_console_event(console)
        log_page_error_event(RuntimeError(_SECRET))
        log_request_failed_event(request)
        log_response_event(response)

    joined = "\n".join(records)
    assert _SECRET not in joined
    # Stable event fields survive.
    assert "type=error" in joined
    assert "resource_type=image" in joined
    assert "status=500" in joined


@pytest.mark.anyio
async def test_resource_resolve_failure_log_is_payload_free() -> None:
    from nonebot_plugin_htmlrender.adapters.resources import (  # noqa: PLC0415
        AnyioWorkerExecutor,
        CompositeResourceReader,
        ConfiguredLocalAccessPolicy,
        RemoteTransportExecutor,
    )
    from nonebot_plugin_htmlrender.resources.config import (  # noqa: PLC0415
        ResourceStrategy,
    )
    from nonebot_plugin_htmlrender.resources.service import (  # noqa: PLC0415
        ResourceService,
    )

    resources = ResourceService(
        reader=CompositeResourceReader(
            AnyioWorkerExecutor(),
            remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
        ),
        local_access=ConfiguredLocalAccessPolicy(allowed_roots=(), allow_any=True),
        strategy=ResourceStrategy(),
    )

    class _RaisingResolver:
        def resolve(
            self, value: object, *, template_base: Path | None = None
        ) -> object:
            del value, template_base
            raise RuntimeError(f"boom {_SECRET}")

    secret_value = f"./{_SECRET}/missing.png"
    with _captured_logs() as records:
        # Non-strict custom resolver failure must log without the resource
        # value or the raised error message.
        result = await resources.resolve_template_vars(
            {"asset": secret_value},
            resolver=_RaisingResolver(),
            strict=False,
        )

    assert result.value == {"asset": secret_value}
    assert _SECRET not in "\n".join(records)
