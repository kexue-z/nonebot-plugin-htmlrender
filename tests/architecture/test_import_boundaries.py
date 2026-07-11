"""Architecture guardrails for the 0.8 layering.

Static AST scan of every module in the package. The rules describe the
*target* architecture; edges that still exist in the legacy code base are
tracked in ``LEGACY_EDGES`` and must shrink phase by phase. The test fails
both on new violations and on stale allowlist entries, so the allowlist can
only ratchet down.

Known limitation: string-based lazy imports (``import_module("...")``) are
not covered here; the final acceptance sweep handles those separately.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = "nonebot_plugin_htmlrender"
PACKAGE_ROOT = Path(__file__).resolve().parents[2] / PACKAGE


@dataclass(frozen=True)
class LayerRule:
    """One directed dependency ban between architectural layers."""

    name: str
    scopes: tuple[str, ...]
    banned: tuple[str, ...]
    excluded_scopes: tuple[str, ...] = ()
    allowed: tuple[str, ...] = ()


def _absolute(scope: str) -> str:
    return f"{PACKAGE}.{scope}"


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


DOMAIN_SCOPES = ("rendering", "application", "preparation", "resources")

DOMAIN_BANNED = (
    _absolute("adapters"),
    _absolute("bootstrap"),
    _absolute("utils.telemetry"),
    _absolute("backend"),
    _absolute("config"),
    _absolute("render"),
    _absolute("browser"),
    _absolute("data_source"),
    _absolute("_compat"),
    _absolute("_bootstrap"),
    "nonebot",
)

RULES: tuple[LayerRule, ...] = (
    LayerRule(
        name="domain packages must not import adapters/bootstrap/telemetry/legacy",
        scopes=DOMAIN_SCOPES,
        # resources.filehost is an AssetPublisher adapter by design; it moves
        # to adapters/ in the physical-migration phase and is scanned then.
        excluded_scopes=("resources.filehost",),
        banned=DOMAIN_BANNED,
        allowed=("nonebot.log",),
    ),
    LayerRule(
        name="resources must not import higher layers",
        scopes=("resources",),
        excluded_scopes=("resources.filehost",),
        banned=(
            _absolute("preparation"),
            _absolute("application"),
            _absolute("rendering"),
            _absolute("api"),
            _absolute("providers"),
        ),
    ),
    LayerRule(
        name="preparation must not import higher layers",
        scopes=("preparation",),
        banned=(
            _absolute("application"),
            _absolute("rendering"),
            _absolute("api"),
            _absolute("providers"),
        ),
    ),
    LayerRule(
        name="takumi must not import playwright",
        scopes=("backend.takumi", "adapters.takumi"),
        banned=(_absolute("backend.playwright"), _absolute("adapters.playwright")),
    ),
    LayerRule(
        name="playwright must not import takumi",
        scopes=("backend.playwright", "adapters.playwright"),
        banned=(_absolute("backend.takumi"), _absolute("adapters.takumi")),
    ),
)

# (module, imported target) -> planned removal note. Shrinks per phase;
# stale entries fail the test so the ratchet only moves one way.
LEGACY_EDGES: dict[tuple[str, str], str] = {}


@dataclass(frozen=True)
class ImportEdge:
    module: str
    target: str
    lineno: int = field(compare=False)

    def key(self) -> tuple[str, str]:
        return (self.module, self.target)


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_import_base(
    module: str,
    *,
    is_package: bool,
    level: int,
    target: str | None,
) -> str:
    if level == 0:
        return target or ""
    parts = module.split(".")
    if not is_package:
        parts.pop()
    for _ in range(level - 1):
        parts.pop()
    if target:
        parts.extend(target.split("."))
    return ".".join(parts)


def _collect_edges() -> list[ImportEdge]:
    edges: list[ImportEdge] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        module = _module_name(path)
        is_package = path.name == "__init__.py"
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                edges.extend(
                    ImportEdge(module, alias.name, node.lineno) for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_import_base(
                    module,
                    is_package=is_package,
                    level=node.level,
                    target=node.module,
                )
                edges.extend(
                    ImportEdge(
                        module,
                        f"{base}.{alias.name}" if base else alias.name,
                        node.lineno,
                    )
                    for alias in node.names
                )
    return edges


def _in_scope(module: str, rule: LayerRule) -> bool:
    if not any(_matches(module, _absolute(scope)) for scope in rule.scopes):
        return False
    return not any(_matches(module, _absolute(scope)) for scope in rule.excluded_scopes)


def _is_banned(target: str, rule: LayerRule) -> bool:
    if any(_matches(target, prefix) for prefix in rule.allowed):
        return False
    return any(_matches(target, prefix) for prefix in rule.banned)


def _find_violations() -> dict[tuple[str, str], str]:
    violations: dict[tuple[str, str], str] = {}
    for edge in _collect_edges():
        for rule in RULES:
            if _in_scope(edge.module, rule) and _is_banned(edge.target, rule):
                violations[edge.key()] = (
                    f"{edge.module}:{edge.lineno} imports {edge.target}"
                    f" (rule: {rule.name})"
                )
    return violations


def test_layer_rules_hold_outside_legacy_allowlist() -> None:
    violations = _find_violations()

    new_violations = [
        description
        for key, description in sorted(violations.items())
        if key not in LEGACY_EDGES
    ]
    assert not new_violations, (
        "New forbidden import edges introduced:\n  " + "\n  ".join(new_violations)
    )


def test_legacy_allowlist_has_no_stale_entries() -> None:
    violations = _find_violations()

    stale = [
        f"{module} -> {target} ({note})"
        for (module, target), note in sorted(LEGACY_EDGES.items())
        if (module, target) not in violations
    ]
    assert not stale, (
        "LEGACY_EDGES entries no longer occur; remove them to keep the "
        "ratchet honest:\n  " + "\n  ".join(stale)
    )
