"""Legacy backend contracts, kept import-light until the physical migration.

Only the engine-neutral protocol types are re-exported here; the registry in
``.factory`` must be imported explicitly so that backend submodule imports
never load NoneBot configuration as a side effect.
"""

from .base import (
    Backend,
    BackendCapability,
    BackendExtension,
    RenderRuntime,
    RenderSession,
)

__all__ = [
    "Backend",
    "BackendCapability",
    "BackendExtension",
    "RenderRuntime",
    "RenderSession",
]
