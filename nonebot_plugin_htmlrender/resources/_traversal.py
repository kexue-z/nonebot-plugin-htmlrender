"""Bounded planning and reconstruction for template variable trees."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import islice
from typing import Literal, TypeAlias, TypeVar

from .errors import ResourceResolutionError

_ContainerKind: TypeAlias = Literal["mapping", "tuple", "list", "set", "sequence"]
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class ResourceTraversalBudget:
    """Hard bounds for one template-variable resolution operation."""

    max_nodes: int = 10_000
    max_depth: int = 64
    max_concurrency: int = 16

    def __post_init__(self) -> None:
        if type(self.max_nodes) is not int or self.max_nodes <= 0:
            raise ValueError("Resource traversal max_nodes must be a positive integer.")
        if type(self.max_depth) is not int or self.max_depth < 0:
            raise ValueError(
                "Resource traversal max_depth must be a non-negative integer."
            )
        if type(self.max_concurrency) is not int or self.max_concurrency <= 0:
            raise ValueError(
                "Resource traversal max_concurrency must be a positive integer."
            )


@dataclass(frozen=True, slots=True)
class VariableLeaf:
    """One non-container value in traversal order."""

    node_index: int
    path: str
    value: object


@dataclass(frozen=True, slots=True)
class _LeafNode:
    path: str
    value: object


@dataclass(frozen=True, slots=True)
class _ContainerNode:
    kind: _ContainerKind
    keys: tuple[object, ...]
    children: tuple[int, ...]


@dataclass(slots=True)
class _MutableContainerNode:
    kind: _ContainerKind
    keys: tuple[object, ...]
    children: list[int]


_FrozenNode: TypeAlias = _LeafNode | _ContainerNode
_BuildingNode: TypeAlias = _LeafNode | _MutableContainerNode


@dataclass(frozen=True, slots=True)
class _Visit:
    value: object
    depth: int
    parent_index: int | None
    child_slot: int | None
    path: str


@dataclass(frozen=True, slots=True)
class _Exit:
    identity: int


def _bounded_tuple(values: Iterable[_T], max_items: int) -> tuple[_T, ...]:
    items = tuple(islice(values, max_items + 1))
    if len(items) > max_items:
        raise ResourceResolutionError(
            "Template variable tree exceeds the configured node traversal limit."
        )
    return items


def _container_parts(
    value: object,
    *,
    max_children: int,
) -> tuple[_ContainerKind, tuple[object, ...], tuple[object, ...]] | None:
    if isinstance(value, Mapping):
        items = _bounded_tuple(value.items(), max_children)
        return (
            "mapping",
            tuple(key for key, _ in items),
            tuple(item for _, item in items),
        )
    if isinstance(value, tuple):
        return "tuple", (), _bounded_tuple(value, max_children)
    if isinstance(value, list):
        return "list", (), _bounded_tuple(value, max_children)
    if isinstance(value, set):
        return "set", (), _bounded_tuple(value, max_children)
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return "sequence", (), _bounded_tuple(value, max_children)
    return None


def _child_path(
    parent: str,
    kind: _ContainerKind,
    keys: tuple[object, ...],
    index: int,
) -> str:
    if kind == "mapping":
        return f"{parent}[{keys[index]!r}]"
    return f"{parent}[{index}]"


@dataclass(frozen=True, slots=True)
class VariableResolutionPlan:
    """A bounded immutable variable tree with separately resolvable leaves."""

    _nodes: tuple[_FrozenNode, ...]
    _root_index: int
    leaves: tuple[VariableLeaf, ...]

    @classmethod
    def build(
        cls,
        value: object,
        *,
        budget: ResourceTraversalBudget,
    ) -> VariableResolutionPlan:
        nodes: list[_BuildingNode] = []
        active_containers: set[int] = set()
        stack: list[_Visit | _Exit] = [_Visit(value, 0, None, None, "$")]
        root_index: int | None = None
        leaves: list[VariableLeaf] = []

        while stack:
            work = stack.pop()
            if isinstance(work, _Exit):
                active_containers.remove(work.identity)
                continue

            if len(nodes) >= budget.max_nodes:
                raise ResourceResolutionError(
                    "Template variable tree exceeds the configured "
                    f"{budget.max_nodes}-node traversal limit."
                )

            parts = _container_parts(
                work.value,
                max_children=budget.max_nodes - len(nodes) - 1,
            )
            node_index = len(nodes)
            if parts is None:
                node: _BuildingNode = _LeafNode(work.path, work.value)
                leaves.append(VariableLeaf(node_index, work.path, work.value))
            else:
                kind, keys, children = parts
                if work.depth > budget.max_depth:
                    raise ResourceResolutionError(
                        "Template variable tree reaches "
                        f"{work.path} at depth {work.depth}, exceeding the configured "
                        f"depth limit of {budget.max_depth}."
                    )
                identity = id(work.value)
                if identity in active_containers:
                    raise ResourceResolutionError(
                        f"Template variable tree contains a cycle at {work.path}."
                    )
                active_containers.add(identity)
                node = _MutableContainerNode(
                    kind,
                    keys,
                    [-1] * len(children),
                )
                stack.append(_Exit(identity))
                stack.extend(
                    [
                        _Visit(
                            children[index],
                            work.depth + 1,
                            node_index,
                            index,
                            _child_path(work.path, kind, keys, index),
                        )
                        for index in range(len(children) - 1, -1, -1)
                    ]
                )

            nodes.append(node)
            if work.parent_index is None:
                root_index = node_index
            else:
                parent = nodes[work.parent_index]
                if not isinstance(parent, _MutableContainerNode):
                    raise RuntimeError("Traversal plan parent must be a container.")
                if work.child_slot is None:
                    raise RuntimeError("Traversal plan child slot is missing.")
                parent.children[work.child_slot] = node_index

        if root_index is None:
            raise RuntimeError("Traversal plan did not produce a root node.")

        frozen_nodes: list[_FrozenNode] = []
        for node in nodes:
            if isinstance(node, _LeafNode):
                frozen_nodes.append(node)
                continue
            if any(child < 0 for child in node.children):
                raise RuntimeError("Traversal plan contains an unassigned child.")
            frozen_nodes.append(
                _ContainerNode(node.kind, node.keys, tuple(node.children))
            )
        return cls(tuple(frozen_nodes), root_index, tuple(leaves))

    def rebuild(self, resolved: Mapping[int, object]) -> object:
        """Rebuild the original container shape from resolved leaf values."""
        values: list[object] = [None] * len(self._nodes)
        for index in range(len(self._nodes) - 1, -1, -1):
            node = self._nodes[index]
            if isinstance(node, _LeafNode):
                values[index] = resolved.get(index, node.value)
                continue

            children = [values[child] for child in node.children]
            if node.kind == "mapping":
                values[index] = dict(zip(node.keys, children, strict=True))
            elif node.kind == "tuple":
                values[index] = tuple(children)
            elif node.kind in {"list", "sequence"}:
                values[index] = children
            else:
                try:
                    values[index] = set(children)
                except TypeError as error:
                    raise ResourceResolutionError(
                        "Resolved set items must remain hashable.",
                        source=error,
                    ) from error
        return values[self._root_index]


__all__ = ["ResourceTraversalBudget", "VariableResolutionPlan"]
