"""Process-wide coordination of Playwright driver spawns.

``PLAYWRIGHT_BROWSERS_PATH`` is process-global state, so exactly one driver
spawn may snapshot/write/restore it at a time. The coordinator is the sole
owner of that variable: it serializes spawns with a backend-neutral
``threading.Lock`` (no module-level AnyIO primitive, so it never binds to
the first event loop) and scopes the environment through
``browsers_path_scope``. Waiting for the mutex happens on a worker hop with
a private limiter so the event loop stays free and the default AnyIO
limiter is untouched; a cancelled waiter hands the mutex back safely even
when the acquiring thread wins the race.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import threading
from typing import TYPE_CHECKING, final

from anyio import CapacityLimiter
from anyio.to_thread import run_sync

from .install_state import browsers_path_scope

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .config import PlaywrightConfig


@final
class _MutexHandoff:
    """Acquire a mutex from a worker thread with abandon-safe hand-back."""

    def __init__(self, mutex: threading.Lock) -> None:
        self._mutex = mutex
        self._state = threading.Lock()
        self._abandoned = False
        self._acquired = False
        self._released = False

    def acquire(self) -> None:
        self._mutex.acquire()
        with self._state:
            self._acquired = True
            if self._abandoned:
                self._mutex.release()
                self._released = True

    def abandon(self) -> None:
        with self._state:
            self._abandoned = True
            if self._acquired and not self._released:
                self._mutex.release()
                self._released = True


@final
class PlaywrightDriverSpawnCoordinator:
    """Sole owner of ``PLAYWRIGHT_BROWSERS_PATH`` during driver spawns."""

    def __init__(self) -> None:
        self._mutex = threading.Lock()

    @asynccontextmanager
    async def browsers_path_guard(
        self,
        config: PlaywrightConfig,
    ) -> AsyncIterator[None]:
        """Hold the spawn mutex and the scoped browser-store environment.

        The scope covers only the environment snapshot and the driver spawn
        performed inside the ``async with`` body — never browser lifetime —
        so concurrent applications are not serialized beyond the spawn.
        """
        handoff = _MutexHandoff(self._mutex)
        try:
            await run_sync(
                handoff.acquire,
                limiter=CapacityLimiter(1),
                abandon_on_cancel=True,
            )
        except BaseException:
            handoff.abandon()
            raise
        try:
            with browsers_path_scope(config):
                yield
        finally:
            self._mutex.release()


DRIVER_SPAWN_COORDINATOR = PlaywrightDriverSpawnCoordinator()

__all__ = [
    "DRIVER_SPAWN_COORDINATOR",
    "PlaywrightDriverSpawnCoordinator",
]
