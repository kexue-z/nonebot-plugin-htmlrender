"""Contracts keeping the 0.8 documentation aligned with the public surface."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "nonebot_plugin_htmlrender"
PACKAGE_ROOT = ROOT / PACKAGE
SETTINGS_PATH = PACKAGE_ROOT / "bootstrap" / "settings.py"
MERMAID_RUNTIME_PATH = (
    ROOT / "docs" / "assets" / "javascripts" / "mermaid-11.16.0.min.js"
)
MERMAID_LICENSE_PATH = ROOT / "docs" / "assets" / "licenses" / "mermaid-11.16.0.txt"
MERMAID_RUNTIME_SHA256 = (
    "74d7c46dabca328c2294733910a8aa1ed0c37451776e8d5295da38a2b758fb9b"
)

MIGRATION_CONTRACT_ALLOWLIST: Mapping[Path, str] = {
    Path("docs/users/migration-v080.md"): "0.7 to 0.8 contract mapping",
    Path("docs/users/migration-v072.md"): "historical 0.7.2 migration record",
    Path("docs/users/migration.md"): "historical pre-0.8 migration record",
}

EXPECTED_PUBLIC_EXPORTS = frozenset(
    {
        "Application",
        "RasterOptions",
        "RenderedHtml",
        "RenderedImage",
        "Renderer",
        "ResourcePolicy",
        "get_default_application",
        "get_default_renderer",
        "prepare_html",
        "prepare_markdown",
        "prepare_template",
        "prepare_text",
        "rasterize_html",
        "render_html",
        "render_markdown",
        "render_template",
        "render_template_html",
        "render_text",
        "resolve_template_vars",
        "to_resource_url",
    }
)

EXPECTED_CONFIG_PATHS = frozenset(
    {
        "render.observability.prometheus",
        "render.observability.sentry",
        "render.provider",
        "render.provider_config",
        "render.resources.cache.max_bytes",
        "render.resources.cache.max_entries",
        "render.resources.cache.max_resource_bytes",
        "render.resources.cache.revalidate_seconds",
        "render.resources.local_access.allow_any_path",
        "render.resources.local_access.allowed_paths",
        "render.resources.templates.environment_cache_max_entries",
        "render.startup",
    }
)

EXPECTED_ARCHITECTURE_TERMS = frozenset(
    {
        "AssetPublisher",
        "EngineBindings",
        "EngineProvider",
        "ExecutionLeaseProvider",
        "LocalAccessPolicy",
        "ProviderDependencies",
        "ProviderResources",
        "ResourceContent",
        "ResourceReader",
        "ResourceRef",
        "ResourceService",
        "ResourceStrategy",
        "WorkerExecutor",
    }
)

_REMOVED_API_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "removed Backend/Render type",
        re.compile(
            r"\b(?:"
            r"BackendCapability|BackendExtension|BackendStatus|RenderBackend|"
            r"RenderRuntime|RenderSession|RenderContext|"
            r"Supports[A-Za-z0-9_]*Backend"
            r")\b|`(?:Backend|Render)`"
        ),
    ),
    (
        "removed Backend/Render function",
        re.compile(
            r"\b(?:"
            r"available_render_backends|build_backend|capture_html_element|"
            r"create_render|get_backend|get_default_render|get_new_page|get_render|"
            r"get_render_backend_status|get_render_context|is_render_backend_available|"
            r"is_render_backend_registered|list_render_backend_statuses|probe_render|"
            r"register_backend|registered_render_backends|require_render_extension|"
            r"shutdown_render|startup_render|unavailable_render_backends"
            r")\b"
        ),
    ),
    (
        "removed compatibility API",
        re.compile(
            r"\b(?:"
            r"html_to_pic|md_to_pic|shutdown_htmlrender|startup_htmlrender|"
            r"template_to_html|template_to_pic|text_to_pic"
            r")\b"
        ),
    ),
    (
        "removed provider-specific convenience argument",
        re.compile(
            r"\b(?:"
            r"device_scale_factor|image_type|markdown_text|md_path|resolve_resources|"
            r"resource_strict|screenshot_timeout"
            r")\b|\b(?:pages|templates|wait)\s*="
        ),
    ),
    (
        "removed public module",
        re.compile(r"\bnonebot_plugin_htmlrender\.(?:backend|config|render)(?:\b|\.)"),
    ),
)

_PYTHON_FENCE = re.compile(
    r"(?ms)^(?P<indent>[ \t]*)```(?:python|py)(?:[^\n]*)\n"
    r"(?P<body>.*?)(?P=indent)```[ \t]*$"
)


@dataclass(frozen=True)
class PythonSource:
    path: Path
    lineno: int
    source: str


def _relative(path: Path) -> Path:
    return path.relative_to(ROOT)


def _documentation_files() -> list[Path]:
    files = [ROOT / "README.md"]
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    for path in sorted((ROOT / "examples").rglob("*")):
        if not path.is_file():
            continue
        if any(part in {".venv", "__pycache__"} for part in path.parts):
            continue
        if path.suffix in {
            ".md",
            ".py",
            ".toml",
            ".yaml",
            ".yml",
        } or path.name.startswith(".env"):
            files.append(path)
    return files


def _current_contract_files() -> list[Path]:
    return [
        path
        for path in _documentation_files()
        if _relative(path) not in MIGRATION_CONTRACT_ALLOWLIST
    ]


def _literal_string_sequence(path: Path, name: str) -> tuple[str, ...]:
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            matches = any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            )
            value_node = node.value
        elif isinstance(node, ast.AnnAssign):
            matches = isinstance(node.target, ast.Name) and node.target.id == name
            value_node = node.value
        else:
            continue
        if not matches:
            continue
        if value_node is None:
            continue
        value = ast.literal_eval(value_node)
        if isinstance(value, (list, tuple)) and all(
            isinstance(item, str) for item in value
        ):
            return tuple(value)
    raise AssertionError(f"{path} must define a literal string sequence {name}")


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _stale_contract_occurrences() -> list[str]:
    patterns = list(_REMOVED_API_PATTERNS)
    patterns.extend(
        (
            "removed flat configuration key",
            re.compile(rf"\b{re.escape(key)}\b", re.IGNORECASE),
        )
        for key in _literal_string_sequence(SETTINGS_PATH, "LEGACY_CONFIG_KEYS")
    )
    occurrences: list[str] = []
    for path in _current_contract_files():
        text = path.read_text("utf-8")
        for description, pattern in patterns:
            occurrences.extend(
                (
                    f"{_relative(path)}:{_line_number(text, match.start())}: "
                    f"{match.group(0)!r} ({description})"
                )
                for match in pattern.finditer(text)
            )
    return occurrences


def test_historical_contract_allowlist_is_explicit_and_not_stale() -> None:
    missing = [
        f"{path} ({reason})"
        for path, reason in MIGRATION_CONTRACT_ALLOWLIST.items()
        if not (ROOT / path).is_file()
    ]
    assert not missing, "Stale migration allowlist entries:\n  " + "\n  ".join(missing)


def test_current_documentation_and_examples_do_not_teach_removed_contracts() -> None:
    occurrences = _stale_contract_occurrences()
    assert not occurrences, (
        "Removed 0.7/alpha contracts may only appear in explicitly allowlisted "
        "migration documents:\n  " + "\n  ".join(occurrences)
    )


def _python_sources() -> Iterator[PythonSource]:
    markdown_paths = [ROOT / "README.md"]
    markdown_paths.extend(sorted((ROOT / "docs").rglob("*.md")))
    markdown_paths.extend(sorted((ROOT / "examples").rglob("*.md")))
    for path in markdown_paths:
        text = path.read_text("utf-8")
        for match in _PYTHON_FENCE.finditer(text):
            yield PythonSource(
                path=_relative(path),
                lineno=_line_number(text, match.start("body")),
                source=textwrap.dedent(match.group("body")),
            )
    for path in sorted((ROOT / "examples").rglob("*.py")):
        if any(part in {".venv", "__pycache__"} for part in path.parts):
            continue
        yield PythonSource(
            path=_relative(path),
            lineno=1,
            source=path.read_text("utf-8"),
        )


def _parse_python_source(
    source: PythonSource,
) -> tuple[ast.Module | None, str | None]:
    try:
        return ast.parse(source.source, filename=str(source.path)), None
    except SyntaxError as error:
        lineno = source.lineno + (error.lineno or 1) - 1
        return None, f"{source.path}:{lineno}: {error.msg}"


def _parse_python_sources() -> tuple[list[tuple[PythonSource, ast.Module]], list[str]]:
    parsed: list[tuple[PythonSource, ast.Module]] = []
    errors: list[str] = []
    for source in _python_sources():
        tree, error = _parse_python_source(source)
        if error is not None:
            errors.append(error)
        elif tree is not None:
            parsed.append((source, tree))
    return parsed, errors


def test_python_examples_and_documentation_fences_parse() -> None:
    _, errors = _parse_python_sources()
    assert not errors, "Invalid Python examples:\n  " + "\n  ".join(errors)


def test_mermaid_runtime_is_pinned_and_self_hosted() -> None:
    config = (ROOT / "mkdocs.yml").read_text("utf-8")
    runtime = MERMAID_RUNTIME_PATH.read_bytes()
    license_text = MERMAID_LICENSE_PATH.read_text("utf-8")

    assert "assets/javascripts/mermaid-11.16.0.min.js" in config
    assert "name: mermaid" in config
    assert sha256(runtime).hexdigest() == MERMAID_RUNTIME_SHA256
    assert b'globalThis["mermaid"]' in runtime
    assert "The MIT License (MIT)" in license_text


def _top_level_exports() -> frozenset[str]:
    return frozenset(_literal_string_sequence(PACKAGE_ROOT / "__init__.py", "__all__"))


def test_required_public_surface_is_exported_and_documented() -> None:
    exports = _top_level_exports()
    missing_exports = sorted(EXPECTED_PUBLIC_EXPORTS - exports)
    current_text = "\n".join(
        path.read_text("utf-8") for path in _current_contract_files()
    )
    missing_docs = sorted(
        symbol
        for symbol in EXPECTED_PUBLIC_EXPORTS
        if re.search(rf"\b{re.escape(symbol)}\b", current_text) is None
    )
    assert not missing_exports, (
        "Required top-level public exports are missing: " + ", ".join(missing_exports)
    )
    assert not missing_docs, (
        "Current documentation does not cover public symbols: "
        + ", ".join(missing_docs)
    )


def test_documented_top_level_imports_exist() -> None:
    exports = _top_level_exports()
    parsed, _ = _parse_python_sources()
    missing: list[str] = []
    for source, tree in parsed:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != PACKAGE:
                continue
            for alias in node.names:
                if alias.name not in exports:
                    lineno = source.lineno + node.lineno - 1
                    missing.append(f"{source.path}:{lineno}: {alias.name}")
    assert not missing, (
        f"Examples import names absent from {PACKAGE}.__all__:\n  "
        + "\n  ".join(missing)
    )


def test_maintainer_docs_cover_the_final_architecture_vocabulary() -> None:
    architecture_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted(
            (ROOT / "docs" / "maintainers" / "architecture").rglob("*.md")
        )
    )
    missing = sorted(
        term
        for term in EXPECTED_ARCHITECTURE_TERMS
        if re.search(rf"\b{re.escape(term)}\b", architecture_text) is None
    )
    assert not missing, (
        "Maintainer architecture documentation is missing final concepts: "
        + ", ".join(missing)
    )


def _annotation_name(annotation: ast.expr) -> str | None:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    return None


def _is_class_variable(annotation: ast.expr) -> bool:
    return (
        isinstance(annotation, ast.Subscript)
        and _annotation_name(annotation.value) == "ClassVar"
    )


def _config_model_fields() -> dict[str, dict[str, str | None]]:
    tree = ast.parse(SETTINGS_PATH.read_text("utf-8"), filename=str(SETTINGS_PATH))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}

    def inherits_base_model(name: str, seen: frozenset[str] = frozenset()) -> bool:
        if name in seen or name not in classes:
            return False
        bases = {
            base_name
            for base in classes[name].bases
            if (base_name := _annotation_name(base)) is not None
        }
        return "BaseModel" in bases or any(
            inherits_base_model(base, seen | {name}) for base in bases
        )

    models: dict[str, dict[str, str | None]] = {}
    for name, node in classes.items():
        if not inherits_base_model(name):
            continue
        fields: dict[str, str | None] = {}
        for statement in node.body:
            if (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and not _is_class_variable(statement.annotation)
            ):
                fields[statement.target.id] = _annotation_name(statement.annotation)
        models[name] = fields
    return models


def _config_leaf_paths() -> frozenset[str]:
    models = _config_model_fields()
    leaves: set[str] = set()

    def visit(model: str, prefix: tuple[str, ...]) -> None:
        for field_name, annotation in models[model].items():
            path = (*prefix, field_name)
            if annotation in models:
                visit(annotation, path)
            else:
                leaves.add(".".join(path))

    assert "RenderPluginConfig" in models, "RenderPluginConfig must remain a BaseModel"
    visit("RenderPluginConfig", ())
    return frozenset(leaves)


def test_unified_config_schema_and_documentation_stay_in_sync() -> None:
    schema_paths = _config_leaf_paths()
    missing_schema = sorted(EXPECTED_CONFIG_PATHS - schema_paths)
    config_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((ROOT / "docs" / "users" / "config").rglob("*.md"))
    )
    missing_docs = sorted(path for path in schema_paths if path not in config_text)
    assert not missing_schema, (
        "Unified render configuration lost required paths: " + ", ".join(missing_schema)
    )
    assert not missing_docs, (
        "Configuration fields must be documented with their full dotted paths: "
        + ", ".join(missing_docs)
    )
