"""Provider resolution: explicit overrides, first-party ids, entry points.

Only the provider selected by configuration is ever imported. Explicit
providers passed to the composition root take precedence (tests, embedding);
``htmlkit``, ``playwright``, and ``takumi`` are reserved for the first-party
adapters and cannot be overridden through entry points.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, cast

from nonebot_plugin_htmlrender.rendering.errors import (
    ProviderNotFound,
    ProviderUnavailable,
)

from .sdk import (
    ENTRY_POINT_GROUP,
    HTMLKIT_PROVIDER_ID,
    PLAYWRIGHT_PROVIDER_ID,
    RESERVED_PROVIDER_IDS,
    TAKUMI_PROVIDER_ID,
    EngineProvider,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .sdk import EngineId

_FIRST_PARTY_MODULES: dict[str, str] = {
    HTMLKIT_PROVIDER_ID: "nonebot_plugin_htmlrender.adapters.htmlkit.provider",
    PLAYWRIGHT_PROVIDER_ID: "nonebot_plugin_htmlrender.adapters.playwright.provider",
    TAKUMI_PROVIDER_ID: "nonebot_plugin_htmlrender.adapters.takumi.provider",
}
_FIRST_PARTY_ATTRIBUTE = "PROVIDER"


def _validate_provider(
    candidate: object,
    *,
    origin: str,
) -> EngineProvider[object]:
    if not isinstance(candidate, EngineProvider):
        raise ProviderUnavailable(
            f"Object from {origin} does not implement the EngineProvider "
            f"protocol: {candidate!r}."
        )
    return cast("EngineProvider[object]", candidate)


def _validate_explicit(
    providers: Sequence[EngineProvider[object]],
) -> dict[str, EngineProvider[object]]:
    by_id: dict[str, EngineProvider[object]] = {}
    for provider in providers:
        validated = _validate_provider(provider, origin="explicit override")
        if validated.id in by_id:
            raise ProviderUnavailable(
                f"Duplicate explicit provider id `{validated.id}`."
            )
        by_id[validated.id] = validated
    return by_id


def _load_first_party(provider_id: EngineId) -> EngineProvider[object]:
    module = import_module(_FIRST_PARTY_MODULES[provider_id])
    return _validate_provider(
        getattr(module, _FIRST_PARTY_ATTRIBUTE),
        origin=f"first-party module for `{provider_id}`",
    )


def _load_entry_point(provider_id: EngineId) -> EngineProvider[object]:
    matches = [
        entry_point
        for entry_point in entry_points(group=ENTRY_POINT_GROUP)
        if entry_point.name == provider_id
    ]
    if not matches:
        raise ProviderNotFound(
            f"No provider named `{provider_id}` is installed. Install a package "
            f"exposing it through the `{ENTRY_POINT_GROUP}` entry-point group, "
            "or pass an explicit provider to the composition root."
        )
    if len(matches) > 1:
        distributions = ", ".join(str(entry_point.dist) for entry_point in matches)
        raise ProviderUnavailable(
            f"Multiple entry points register provider id `{provider_id}` "
            f"({distributions}); uninstall the conflicting distributions."
        )

    loaded = matches[0].load()
    candidate = loaded() if isinstance(loaded, type) else loaded
    provider = _validate_provider(
        candidate,
        origin=f"entry point `{provider_id}`",
    )
    if provider.id != provider_id:
        raise ProviderUnavailable(
            f"Entry point `{provider_id}` resolved to a provider with "
            f"mismatched id `{provider.id}`."
        )
    return provider


def _reject_reserved_hijack(provider_id: EngineId) -> None:
    hijackers = [
        entry_point
        for entry_point in entry_points(group=ENTRY_POINT_GROUP)
        if entry_point.name == provider_id
    ]
    if hijackers:
        distributions = ", ".join(str(entry_point.dist) for entry_point in hijackers)
        raise ProviderUnavailable(
            f"Provider id `{provider_id}` is reserved for the first-party "
            f"adapter and cannot be overridden by entry points "
            f"({distributions})."
        )


def resolve_provider(
    provider_id: EngineId,
    *,
    explicit: Sequence[EngineProvider[object]] = (),
) -> EngineProvider[object]:
    """Resolve the configured provider without importing any other engine."""
    explicit_by_id = _validate_explicit(explicit)
    override = explicit_by_id.get(provider_id)
    if override is not None:
        return override

    if provider_id in RESERVED_PROVIDER_IDS:
        _reject_reserved_hijack(provider_id)
        return _load_first_party(provider_id)

    return _load_entry_point(provider_id)


__all__ = ["resolve_provider"]
