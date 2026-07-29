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
APPLICATION_EXTENSIONS_PATH = PACKAGE_ROOT / "application" / "extensions.py"
MERMAID_RUNTIME_PATH = (
    ROOT / "docs" / "assets" / "javascripts" / "mermaid-11.16.0.min.js"
)
MERMAID_LICENSE_PATH = ROOT / "docs" / "assets" / "licenses" / "mermaid-11.16.0.txt"
MERMAID_RUNTIME_SHA256 = (
    "74d7c46dabca328c2294733910a8aa1ed0c37451776e8d5295da38a2b758fb9b"
)

DOCUMENTATION_ROOTS: Mapping[str, Path] = {
    "architecture": ROOT / "docs" / "extensions",
    "configuration": ROOT / "docs" / "configuration",
    "migration": ROOT / "docs" / "guides" / "migration",
}

MIGRATION_CONTRACT_ALLOWLIST: Mapping[Path, str] = {
    Path("docs/guides/migration/index.md"): "migration index and removed-key lookup",
    Path("docs/guides/migration/v0.8.md"): "0.7 to 0.8 contract mapping",
    Path("docs/guides/migration/v0.7.2.md"): "historical 0.7.2 migration record",
}

EXPECTED_PUBLIC_EXPORTS = frozenset(
    {
        "Application",
        "ApplicationNotInitialized",
        "ErrorCause",
        "RasterOptions",
        "RenderedHtml",
        "RenderedImage",
        "Renderer",
        "RenderingError",
        "ResourcePolicy",
        "ResourceResolution",
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
        "render.html.max_auto_height",
        "render.html.max_concurrency",
        "render.html.max_device_pixel_ratio",
        "render.html.max_output_bytes",
        "render.html.max_pixels",
        "render.html.max_source_bytes",
        "render.provider",
        "render.provider_config",
        "render.resources.cache.max_bytes",
        "render.resources.cache.max_entries",
        "render.resources.cache.max_resource_bytes",
        "render.resources.cache.revalidate_seconds",
        "render.resources.local_access.allow_any_path",
        "render.resources.local_access.allowed_paths",
        "render.resources.templates.environment_cache_max_entries",
        "render.resources.templates.environment_compiled_cache_size",
        "render.resources.traversal.max_concurrency",
        "render.resources.traversal.max_depth",
        "render.resources.traversal.max_nodes",
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
        "removed first-party extension contract",
        re.compile(
            r"\b(?:"
            r"PLAYWRIGHT_CAPTURE|PLAYWRIGHT_PAGE|TAKUMI_RENDERER|"
            r"HtmlkitApi|PlaywrightCapabilityAdapter|TakumiCapabilityAdapter|"
            r"TakumiApi|TakumiExtension"
            r")\b|\.extensions\.graphics\b|\.extension\(\)"
        ),
    ),
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
_MARKDOWN_FENCE = re.compile(r"^[ \t]*(?P<marker>`{3,}|~{3,})")
_MARKDOWN_LEFT_BLOCK_BOUNDARY = re.compile(
    r"^[ \t]*(?:#{1,6}(?:\s|$)|(?:!!!|\?\?\?)\s+|>|\||<|\{[^}]*\}\s*$)"
)
_MARKDOWN_RIGHT_BLOCK_BOUNDARY = re.compile(
    r"^[ \t]*(?:"
    r"#{1,6}(?:\s|$)|[-+*]\s+|\d+[.)]\s+|(?:!!!|\?\?\?)\s+|>|\||"
    r":\s+|\[\^[^]]+\]:|\[[^]]+\]:|<|\{[^}]*\}\s*$"
    r")"
)
_MARKDOWN_THEMATIC_BREAK = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})\s*$")
_CJK_CHARACTER = re.compile(
    r"[\u2e80-\u2eff\u3000-\u303f\u3040-\u30ff\u31c0-\u31ef"
    r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]"
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


def _cjk_soft_break_occurrences(path: Path) -> list[str]:
    lines = path.read_text("utf-8").splitlines()
    occurrences: list[str] = []
    in_front_matter = bool(lines and lines[0].strip() == "---")
    fence_marker: str | None = None
    previous: str | None = None

    for lineno, line in enumerate(lines, start=1):
        if lineno == 1 and in_front_matter:
            continue
        if in_front_matter:
            if line.strip() == "---":
                in_front_matter = False
            continue

        fence = _MARKDOWN_FENCE.match(line)
        if fence_marker is not None:
            if (
                fence is not None
                and fence.group("marker").startswith(fence_marker[0])
                and len(fence.group("marker")) >= len(fence_marker)
            ):
                fence_marker = None
            previous = None
            continue
        if fence is not None:
            fence_marker = fence.group("marker")
            previous = None
            continue

        if previous is not None:
            left = previous.rstrip()
            right = line.lstrip()
            is_soft_break = bool(
                left
                and right
                and not previous.endswith(("  ", "\\"))
                and _MARKDOWN_LEFT_BLOCK_BOUNDARY.match(previous) is None
                and _MARKDOWN_RIGHT_BLOCK_BOUNDARY.match(line) is None
                and _MARKDOWN_THEMATIC_BREAK.match(previous) is None
                and _MARKDOWN_THEMATIC_BREAK.match(line) is None
            )
            if is_soft_break and (
                _CJK_CHARACTER.match(left[-1]) or _CJK_CHARACTER.match(right[0])
            ):
                occurrences.append(f"{_relative(path)}:{lineno - 1}")
        previous = line if line.strip() else None

    return occurrences


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


def test_canonical_documentation_layout_matches_navigation() -> None:
    navigation = (ROOT / "mkdocs.yml").read_text("utf-8")
    missing_roots = [
        name for name, path in DOCUMENTATION_ROOTS.items() if not path.is_dir()
    ]
    missing_navigation = [
        str(path)
        for path in MIGRATION_CONTRACT_ALLOWLIST
        if path.relative_to("docs").as_posix() not in navigation
    ]
    assert not missing_roots, "Canonical documentation roots are missing: " + ", ".join(
        missing_roots
    )
    assert not missing_navigation, (
        "Migration documents must remain in the MkDocs navigation: "
        + ", ".join(missing_navigation)
    )


def test_current_documentation_and_examples_do_not_teach_removed_contracts() -> None:
    occurrences = _stale_contract_occurrences()
    assert not occurrences, (
        "Removed 0.7/alpha contracts may only appear in explicitly allowlisted "
        "migration documents:\n  " + "\n  ".join(occurrences)
    )


def test_documentation_has_no_cjk_prose_soft_breaks() -> None:
    occurrences = [
        occurrence
        for path in _documentation_files()
        if path.suffix == ".md"
        for occurrence in _cjk_soft_break_occurrences(path)
    ]
    assert not occurrences, (
        "CJK prose must not use Markdown soft line breaks because browsers render "
        "them as visible spaces:\n  " + "\n  ".join(occurrences)
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
        for symbol in exports
        if re.search(rf"\b{re.escape(symbol)}\b", current_text) is None
    )
    assert not missing_exports, (
        "Required top-level public exports are missing: " + ", ".join(missing_exports)
    )
    assert not missing_docs, (
        "Current documentation does not cover top-level public symbols: "
        + ", ".join(missing_docs)
    )


def _application_extension_properties() -> frozenset[str]:
    tree = ast.parse(
        APPLICATION_EXTENSIONS_PATH.read_text("utf-8"),
        filename=str(APPLICATION_EXTENSIONS_PATH),
    )
    extension_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ApplicationExtensions"
    )
    return frozenset(
        node.name
        for node in extension_class.body
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(decorator, ast.Name) and decorator.id == "property"
            for decorator in node.decorator_list
        )
    )


def test_first_party_extension_properties_are_documented() -> None:
    properties = _application_extension_properties()
    assert properties == {"playwright", "takumi", "pillow", "skia"}
    current_text = "\n".join(
        path.read_text("utf-8") for path in _current_contract_files()
    )
    missing = sorted(
        name
        for name in properties
        if re.search(rf"\bextensions\.{re.escape(name)}\b", current_text) is None
    )
    assert not missing, (
        "First-party Application.extensions properties are undocumented: "
        + ", ".join(missing)
    )


def test_backend_runtime_dependency_boundaries_are_documented() -> None:
    playwright_text = (
        ROOT / "docs" / "configuration" / "providers" / "playwright.md"
    ).read_text("utf-8")
    skia_text = (ROOT / "docs" / "configuration" / "graphics" / "skia.md").read_text(
        "utf-8"
    )
    provider_matrix = (ROOT / "docs" / "start" / "choosing-provider.md").read_text(
        "utf-8"
    )
    troubleshooting_text = (
        ROOT / "docs" / "configuration" / "troubleshooting.md"
    ).read_text("utf-8")
    remote_playwright_text = (
        ROOT / "docs" / "configuration" / "remote-playwright.md"
    ).read_text("utf-8")

    assert "uv run playwright install --with-deps chromium" in playwright_text
    assert "只安装 Playwright Python client" in playwright_text
    assert "首选：Docker 远程 Playwright" in playwright_text
    assert "第二选项：Bot 宿主机本地 Playwright" in playwright_text
    assert "client 与 browser revision 强一致" in playwright_text
    assert "不得让不同项目虚拟环境共享该目录" in playwright_text
    assert "PLAYWRIGHT_BROWSERS_PATH" in playwright_text
    assert "精确匹配的 browser revision" in troubleshooting_text
    assert "WS 版本门禁与启动探测" in remote_playwright_text
    assert "版本门禁 fail-open" in remote_playwright_text
    assert "CDP 模式不执行 Playwright client/server 版本门禁" in remote_playwright_text
    assert "软门禁不能证明任意版本组合兼容" in remote_playwright_text
    for dependency in (
        "libEGL.so.1",
        "libGL.so.1",
        "libexpat.so.1",
        "libegl1",
        "libgl1",
        "libexpat1",
    ):
        assert f"`{dependency}`" in skia_text
    assert 'uv run python3 -c "import skia"' in skia_text
    for engine in ("Playwright", "HTMLKit", "Takumi", "Pillow", "Skia"):
        assert re.search(rf"^\| {engine} \|", provider_matrix, flags=re.MULTILINE)


def test_cache_components_and_public_invalidation_boundaries_are_documented() -> None:
    cache_guide_path = ROOT / "docs" / "guides" / "cache-lifecycle.md"
    cache_guide = cache_guide_path.read_text("utf-8")
    navigation = (ROOT / "mkdocs.yml").read_text("utf-8")
    resource_reference = (ROOT / "docs" / "configuration" / "resources.md").read_text(
        "utf-8"
    )
    template_guide = (
        ROOT / "docs" / "guides" / "templates-and-resources.md"
    ).read_text("utf-8")
    takumi_reference = (
        ROOT / "docs" / "configuration" / "providers" / "takumi.md"
    ).read_text("utf-8")

    assert "guides/cache-lifecycle.md" in navigation
    for cache_name in (
        "`resource`",
        "`template_environment`",
        "`filehost`",
        "`takumi_compiled`",
    ):
        assert cache_name in cache_guide
    assert "`app.resources.clear()` 只清理当前 Application" in cache_guide
    assert "不会清理 Jinja Environment" in cache_guide
    assert "filter 的名称和 callable 身份" in cache_guide
    assert "无法通过单纯增加内存解决" in cache_guide
    assert "api.compiled_cache_stats" in cache_guide
    assert "refresh=True" in resource_reference
    assert "自定义 Jinja filter" in template_guide
    assert "compiled_cache_stats" in takumi_reference


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
        for path in sorted(DOCUMENTATION_ROOTS["architecture"].rglob("*.md"))
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
        for path in sorted(DOCUMENTATION_ROOTS["configuration"].rglob("*.md"))
    )
    missing_docs = sorted(path for path in schema_paths if path not in config_text)
    assert not missing_schema, (
        "Unified render configuration lost required paths: " + ", ".join(missing_schema)
    )
    assert not missing_docs, (
        "Configuration fields must be documented with their full dotted paths: "
        + ", ".join(missing_docs)
    )
