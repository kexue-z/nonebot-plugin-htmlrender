"""Legacy availability result type shared by the engine adapters.

The old backend registry and engine-selection machinery are gone; provider
selection happens exclusively in the provider SDK discovery.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BackendAvailability:
    """后端运行环境检测结果。

    Attributes:
        available: 当前环境是否可用此后端。
        reason: 不可用时的原因描述，可用时为 ``None``。
    """

    available: bool
    reason: str | None = None


__all__ = ["BackendAvailability"]
