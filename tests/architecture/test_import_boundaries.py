"""Target-state architecture guardrails for the 0.8 layering.

The scan is deliberately independent from importing the package: importing the
top-level plugin executes the NoneBot composition root, while these checks must
also work in a bare test process.  Both ordinary imports and literal lazy
imports participate in the same dependency rules.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
import re

PACKAGE = "nonebot_plugin_htmlrender"
PACKAGE_ROOT = Path(__file__).resolve().parents[2] / PACKAGE


@dataclass(frozen=True)
class LayerRule:
    """One directed dependency ban between architectural layers."""

    name: str
    scopes: tuple[str, ...]
    banned: tuple[str, ...]
    allowed: tuple[str, ...] = ()
    runtime_only: bool = False


def _absolute(scope: str) -> str:
    return f"{PACKAGE}.{scope}"


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


CORE_SCOPES = (
    "graphics",
    "raster",
    "rendering",
    "application",
    "preparation",
    "resources",
)

CORE_BANNED = (
    _absolute("adapters"),
    _absolute("api"),
    _absolute("bootstrap"),
    _absolute("telemetry"),
    _absolute("utils.telemetry"),
    "nonebot",
    "opentelemetry",
    "prometheus_client",
    "sentry_sdk",
)

RULES: tuple[LayerRule, ...] = (
    LayerRule(
        name="raster foundation must not depend on other package layers",
        scopes=("raster",),
        banned=(PACKAGE,),
    ),
    LayerRule(
        name="core packages must not depend on hosts or adapters",
        scopes=CORE_SCOPES,
        banned=CORE_BANNED,
        allowed=("nonebot.log",),
    ),
    LayerRule(
        name="resources must not import higher layers",
        scopes=("resources",),
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
        name="rendering must not import the provider SDK",
        scopes=("rendering",),
        banned=(_absolute("providers"),),
    ),
    LayerRule(
        name="graphics contracts must not import HTML or provider layers",
        scopes=("graphics",),
        banned=(
            _absolute("application"),
            _absolute("preparation"),
            _absolute("providers"),
        ),
    ),
    LayerRule(
        name="takumi must not import playwright",
        scopes=("adapters.takumi",),
        banned=(_absolute("adapters.playwright"),),
    ),
    LayerRule(
        name="playwright must not import takumi",
        scopes=("adapters.playwright",),
        banned=(_absolute("adapters.takumi"),),
    ),
    LayerRule(
        name="htmlkit must not import other renderer adapters",
        scopes=("adapters.htmlkit",),
        banned=(
            _absolute("adapters.pillow"),
            _absolute("adapters.playwright"),
            _absolute("adapters.skia"),
            _absolute("adapters.takumi"),
        ),
    ),
    LayerRule(
        name="pillow must not import skia",
        scopes=("adapters.pillow",),
        banned=(_absolute("adapters.skia"),),
    ),
    LayerRule(
        name="skia must not import pillow",
        scopes=("adapters.skia",),
        banned=(_absolute("adapters.pillow"),),
    ),
    LayerRule(
        name="capabilities must not depend on adapters",
        scopes=("capabilities",),
        banned=(_absolute("adapters"),),
    ),
)


@dataclass(frozen=True)
class ImportEdge:
    module: str
    target: str
    lineno: int = field(compare=False)
    kind: str = field(compare=False, default="import")
    type_only: bool = field(compare=False, default=False)


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _type_checking_guarded_nodes(tree: ast.AST) -> frozenset[int]:
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_test(node.test):
            for statement in node.body:
                guarded.update(id(child) for child in ast.walk(statement))
    return frozenset(guarded)


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


def _resolve_lazy_target(raw: str, *, module: str, is_package: bool) -> str:
    if not raw.startswith("."):
        return raw
    relative = raw.lstrip(".")
    return _resolve_import_base(
        module,
        is_package=is_package,
        level=len(raw) - len(relative),
        target=relative or None,
    )


def _lazy_import_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    direct = {"__import__"}
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    modules.add(alias.asname or "importlib")
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    direct.add(alias.asname or alias.name)
    return direct, modules


def _literal_lazy_imports(
    tree: ast.AST,
    *,
    module: str,
    is_package: bool,
) -> list[ImportEdge]:
    direct, modules = _lazy_import_aliases(tree)
    edges: list[ImportEdge] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        is_loader = isinstance(function, ast.Name) and function.id in direct
        is_loader = is_loader or (
            isinstance(function, ast.Attribute)
            and function.attr == "import_module"
            and isinstance(function.value, ast.Name)
            and function.value.id in modules
        )
        if not is_loader:
            continue
        target_node = node.args[0]
        if not (
            isinstance(target_node, ast.Constant) and isinstance(target_node.value, str)
        ):
            continue
        edges.append(
            ImportEdge(
                module=module,
                target=_resolve_lazy_target(
                    target_node.value,
                    module=module,
                    is_package=is_package,
                ),
                lineno=node.lineno,
                kind="literal lazy import",
            )
        )
    return edges


def _collect_edges() -> list[ImportEdge]:
    edges: list[ImportEdge] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        module = _module_name(path)
        is_package = path.name == "__init__.py"
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        guarded = _type_checking_guarded_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                edges.extend(
                    ImportEdge(
                        module,
                        alias.name,
                        node.lineno,
                        type_only=id(node) in guarded,
                    )
                    for alias in node.names
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
                        type_only=id(node) in guarded,
                    )
                    for alias in node.names
                )
        edges.extend(
            _literal_lazy_imports(
                tree,
                module=module,
                is_package=is_package,
            )
        )
    return edges


def _in_scope(module: str, rule: LayerRule) -> bool:
    return any(_matches(module, _absolute(scope)) for scope in rule.scopes)


def _is_banned(target: str, rule: LayerRule) -> bool:
    return not any(_matches(target, prefix) for prefix in rule.allowed) and any(
        _matches(target, prefix) for prefix in rule.banned
    )


def _find_violations() -> list[str]:
    violations: set[str] = set()
    for edge in _collect_edges():
        for rule in RULES:
            if rule.runtime_only and edge.type_only:
                continue
            if _in_scope(edge.module, rule) and _is_banned(edge.target, rule):
                violations.add(
                    f"{edge.module}:{edge.lineno} {edge.kind} {edge.target}"
                    f" (rule: {rule.name})"
                )
    return sorted(violations)


def test_layer_rules_hold_for_static_and_literal_lazy_imports() -> None:
    violations = _find_violations()
    assert not violations, "Forbidden dependency edges:\n  " + "\n  ".join(violations)


def test_runtime_logging_uses_nonebot_log() -> None:
    violations = [
        f"{edge.module}:{edge.lineno} {edge.kind} {edge.target}"
        for edge in _collect_edges()
        if _matches(edge.target, "logging")
        or _matches(edge.target, "loguru")
        or edge.target == "nonebot.logger"
    ]
    assert not violations, (
        "Runtime logging must import `logger` from `nonebot.log`:\n  "
        + "\n  ".join(violations)
    )


def _python_sources(path: Path) -> tuple[Path, ...]:
    if not path.exists():
        return ()
    return tuple(sorted(path.rglob("*.py")))


def test_filehost_adapter_is_not_nested_under_the_resource_core() -> None:
    legacy_adapter = PACKAGE_ROOT / "resources" / "filehost"
    sources = _python_sources(legacy_adapter)
    assert not sources, (
        "resources.filehost is a host adapter and must live under adapters/resources: "
        f"{sources!r}"
    )


def test_observability_adapter_is_not_nested_under_utils() -> None:
    legacy_adapter = PACKAGE_ROOT / "utils" / "telemetry"
    sources = _python_sources(legacy_adapter)
    assert not sources, (
        "telemetry integrates host SDKs and must live under adapters/observability: "
        f"{sources!r}"
    )


def test_transitional_implementation_modules_are_physically_removed() -> None:
    legacy_modules = (
        "adapters/_backend.py",
        "preparation/content.py",
        "preparation/resolve.py",
        "resources/budget.py",
        "resources/cache.py",
        "resources/resolve.py",
        "resources/template.py",
        "resources/weighted_cache.py",
    )
    present = [module for module in legacy_modules if (PACKAGE_ROOT / module).exists()]
    assert not present, f"Transitional implementation modules remain: {present!r}"


def test_literal_lazy_import_collector_handles_supported_loader_forms() -> None:
    tree = ast.parse(
        """
from importlib import import_module as load
import importlib as imports

load("nonebot_plugin_htmlrender.adapters.resources")
imports.import_module("nonebot")
__import__("sentry_sdk")
"""
    )

    edges = _literal_lazy_imports(
        tree,
        module="nonebot_plugin_htmlrender.resources.synthetic",
        is_package=False,
    )

    assert {(edge.target, edge.kind) for edge in edges} == {
        ("nonebot", "literal lazy import"),
        ("nonebot_plugin_htmlrender.adapters.resources", "literal lazy import"),
        ("sentry_sdk", "literal lazy import"),
    }


def test_collector_marks_type_checking_imports_as_type_only() -> None:
    tree = ast.parse(
        """
from typing import TYPE_CHECKING
import typing

if TYPE_CHECKING:
    from nonebot_plugin_htmlrender.adapters.takumi.api import TakumiAPIAdapter

if typing.TYPE_CHECKING:
    import sentry_sdk

import anyio
"""
    )

    guarded = _type_checking_guarded_nodes(tree)
    flagged = {
        node.lineno: id(node) in guarded
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    }

    assert flagged == {2: False, 3: False, 6: True, 9: True, 11: False}


_LOCATOR_NAME = re.compile(
    r"^(?:"
    r"(?:register|set)_[a-z0-9_]*(?:provider|registry|resolver|observer|service)"
    r"|get_[a-z0-9_]*(?:config|settings|provider|registry|resolver|observer|cache|service)"
    r")$"
)


@dataclass(frozen=True)
class LocatorUse:
    module: str
    symbol: str
    lineno: int
    kind: str


def _called_symbol(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _collect_service_locator_uses() -> list[LocatorUse]:
    uses: set[LocatorUse] = set()
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        module = _module_name(path)
        if not any(_matches(module, _absolute(scope)) for scope in CORE_SCOPES):
            continue
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _LOCATOR_NAME.fullmatch(node.name):
                    uses.add(LocatorUse(module, node.name, node.lineno, "definition"))
            elif isinstance(node, ast.Call):
                symbol = _called_symbol(node)
                if symbol is not None and _LOCATOR_NAME.fullmatch(symbol):
                    uses.add(LocatorUse(module, symbol, node.lineno, "call"))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    symbol = alias.asname or alias.name.rsplit(".", 1)[-1]
                    if _LOCATOR_NAME.fullmatch(symbol):
                        uses.add(LocatorUse(module, symbol, node.lineno, "import"))
    return sorted(uses, key=lambda use: (use.module, use.lineno, use.symbol, use.kind))


def test_core_has_no_global_config_or_service_locator_seams() -> None:
    uses = _collect_service_locator_uses()
    details = [f"{use.module}:{use.lineno} {use.kind} {use.symbol}" for use in uses]
    assert not details, (
        "Core layers must receive configuration, observers, caches, and services "
        "through constructor injection:\n  " + "\n  ".join(details)
    )
