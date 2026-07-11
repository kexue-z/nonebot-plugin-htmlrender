"""No-op observer implementations used when integrations are disabled."""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING, final

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


@final
class NoopCacheObserver:
    """Observer that discards every cache statistics delta."""

    def record(
        self,
        cache: str,  # noqa: ARG002 -- protocol-conforming no-op
        events: Mapping[str, int],  # noqa: ARG002 -- protocol-conforming no-op
        entries: int,  # noqa: ARG002 -- protocol-conforming no-op
        resident_bytes: int | None = None,  # noqa: ARG002 -- protocol-conforming no-op
    ) -> None:
        return None
