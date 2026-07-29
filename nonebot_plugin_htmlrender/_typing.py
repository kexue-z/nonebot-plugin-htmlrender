"""Internal helpers for projecting third-party callable signatures."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar
from typing_extensions import Concatenate, ParamSpec

if TYPE_CHECKING:
    from collections.abc import Callable

_Parameters = ParamSpec("_Parameters")
_SourceSelf = TypeVar("_SourceSelf")
_TargetSelf = TypeVar("_TargetSelf")
_ReturnT = TypeVar("_ReturnT")
_CallableT = TypeVar("_CallableT")


def project_method_parameters(
    source: Callable[Concatenate[_SourceSelf, _Parameters], object],
) -> Callable[
    [Callable[Concatenate[_TargetSelf, ...], _ReturnT]],
    Callable[Concatenate[_TargetSelf, _Parameters], _ReturnT],
]:
    """Project a source method's parameters onto a target method."""
    del source

    def decorate(
        target: Callable[Concatenate[_TargetSelf, ...], _ReturnT],
    ) -> Callable[Concatenate[_TargetSelf, _Parameters], _ReturnT]:
        return target

    return decorate


def identity_decorator(target: _CallableT) -> _CallableT:
    """Return a callable unchanged when a projection is static-only."""
    return target


__all__ = ["identity_decorator", "project_method_parameters"]
