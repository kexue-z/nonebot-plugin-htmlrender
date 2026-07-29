"""Installation checks for the pinned HTMLKit compatibility facade."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec

from nonebot_plugin_htmlrender.providers.sdk import ProviderAvailability

SUPPORTED_HTMLKIT_VERSION = "0.1.0rc5"


def htmlkit_availability() -> ProviderAvailability:
    try:
        if find_spec("nonebot_plugin_htmlkit") is None:
            return ProviderAvailability(
                available=False,
                reason=(
                    "Optional dependency `nonebot-plugin-htmlkit==0.1.0rc5` is "
                    "not installed; install nonebot-plugin-htmlrender[htmlkit]."
                ),
            )
    except (ImportError, ValueError) as error:
        return ProviderAvailability(
            available=False,
            reason=f"Cannot locate nonebot_plugin_htmlkit: {error}",
        )

    try:
        installed_version = version("nonebot-plugin-htmlkit")
    except PackageNotFoundError:
        return ProviderAvailability(
            available=False,
            reason="Distribution metadata for `nonebot-plugin-htmlkit` is unavailable.",
        )
    if installed_version != SUPPORTED_HTMLKIT_VERSION:
        return ProviderAvailability(
            available=False,
            reason=(
                f"Unsupported nonebot-plugin-htmlkit version {installed_version!r}; "
                f"expected {SUPPORTED_HTMLKIT_VERSION!r}."
            ),
        )
    return ProviderAvailability(available=True)


__all__ = ["SUPPORTED_HTMLKIT_VERSION", "htmlkit_availability"]
