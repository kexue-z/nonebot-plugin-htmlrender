"""No-op observer implementations used when integrations are disabled."""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING, final

from nonebot_plugin_htmlrender.resources.observation import (
    NoopCacheObserver as NoopCacheObserver,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import AbstractContextManager


@final
class NoopOperationObserver:
    """Observer that ignores every operation."""

    def observe(
        self,
        operation: str,  # noqa: ARG002 -- protocol-conforming no-op
        attributes: Mapping[str, str],  # noqa: ARG002 -- protocol-conforming no-op
    ) -> AbstractContextManager[None]:
        return nullcontext()
