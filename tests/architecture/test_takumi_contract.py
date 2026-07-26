from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = PROJECT_ROOT / "nonebot_plugin_htmlrender/capabilities/takumi.py"
ADAPTER_PATH = PROJECT_ROOT / "nonebot_plugin_htmlrender/adapters/takumi/api.py"
DOCUMENTATION_PATH = PROJECT_ROOT / "docs/reference/capabilities.md"

EXPECTED_METHOD_GROUPS: dict[str, frozenset[str]] = {
    "compile": frozenset(
        {
            "compile_html",
            "compile_keyframes",
            "compile_node",
            "compile_stylesheet",
        }
    ),
    "raster": frozenset({"render_compiled", "render_html", "render_node"}),
    "measure": frozenset({"measure_compiled", "measure_html", "measure_node"}),
    "svg": frozenset({"render_svg_compiled", "render_svg_html", "render_svg_node"}),
    "animation": frozenset(
        {"encode_frames", "render_animation", "render_sequence_at_time"}
    ),
    "font": frozenset({"register_font", "register_font_file", "register_fonts"}),
}
EXPECTED_PROPERTIES = frozenset({"compiled_cache_stats", "registered_font_families"})
EXPECTED_METHODS = frozenset().union(*EXPECTED_METHOD_GROUPS.values())
EXPECTED_TELEMETRY = {name: f"takumi.api.{name}" for name in EXPECTED_METHODS}
# Preserve the established shorter operation name for observability consumers.
EXPECTED_TELEMETRY["render_sequence_at_time"] = "takumi.api.render_sequence"


def _class(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined in {path}")


def _is_property(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(decorator, ast.Name) and decorator.id == "property"
        for decorator in node.decorator_list
    )


def _public_members(
    node: ast.ClassDef,
) -> tuple[set[str], set[str], dict[str, ast.AsyncFunctionDef]]:
    methods: set[str] = set()
    properties: set[str] = set()
    async_methods: dict[str, ast.AsyncFunctionDef] = {}
    for child in node.body:
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if child.name.startswith("_"):
            continue
        if _is_property(child):
            properties.add(child.name)
        else:
            methods.add(child.name)
        if isinstance(child, ast.AsyncFunctionDef):
            async_methods[child.name] = child
    return methods, properties, async_methods


def _tracked_operation(node: ast.AsyncFunctionDef) -> str | None:
    for decorator in node.decorator_list:
        if not (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "_tracked"
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
            and isinstance(decorator.args[0].value, str)
        ):
            continue
        return decorator.args[0].value
    return None


def test_takumi_protocol_and_adapter_match_the_native_contract_matrix() -> None:
    contract_methods, contract_properties, _ = _public_members(
        _class(CONTRACT_PATH, "TakumiAPI")
    )
    adapter_methods, adapter_properties, adapter_async = _public_members(
        _class(ADAPTER_PATH, "TakumiAPIAdapter")
    )

    assert contract_methods == EXPECTED_METHODS
    assert adapter_methods == EXPECTED_METHODS
    assert contract_properties == EXPECTED_PROPERTIES
    assert adapter_properties == EXPECTED_PROPERTIES
    assert set(adapter_async) == EXPECTED_METHODS


def test_every_takumi_operation_has_a_stable_telemetry_name() -> None:
    _, _, adapter_async = _public_members(_class(ADAPTER_PATH, "TakumiAPIAdapter"))

    actual = {name: _tracked_operation(node) for name, node in adapter_async.items()}

    assert actual == EXPECTED_TELEMETRY


def test_takumi_capability_reference_documents_the_complete_matrix() -> None:
    documentation = DOCUMENTATION_PATH.read_text("utf-8")

    for group, methods in EXPECTED_METHOD_GROUPS.items():
        assert f"<!-- takumi:{group} -->" in documentation
        for method in methods:
            assert f"`{method}`" in documentation
    for name in EXPECTED_PROPERTIES:
        assert f"`{name}`" in documentation
