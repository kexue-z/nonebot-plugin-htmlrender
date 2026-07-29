from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from contextlib import AbstractContextManager


class RecordingOperationObserver:
    """Operation observer fake recording (operation, attributes, outcome)."""

    def __init__(self) -> None:
        self.operations: list[tuple[str, dict[str, str], str]] = []

    def observe(
        self,
        operation: str,
        attributes: Mapping[str, str],
    ) -> AbstractContextManager[None]:
        return self._observe(operation, dict(attributes))

    @contextmanager
    def _observe(
        self,
        operation: str,
        attributes: dict[str, str],
    ) -> Iterator[None]:
        try:
            yield
        except BaseException:
            self.operations.append((operation, attributes, "error"))
            raise
        self.operations.append((operation, attributes, "success"))

    def names(self) -> list[str]:
        return [operation for operation, _, _ in self.operations]


@pytest.fixture
def operation_observer() -> RecordingOperationObserver:
    return RecordingOperationObserver()
