"""Stable provider-specific capability contracts and lookup keys."""

from .playwright import (
    PLAYWRIGHT,
    PlaywrightAccess,
)
from .takumi import (
    TAKUMI,
    TakumiAccess,
    TakumiAPI,
)

__all__ = [
    "PLAYWRIGHT",
    "TAKUMI",
    "PlaywrightAccess",
    "TakumiAPI",
    "TakumiAccess",
]
