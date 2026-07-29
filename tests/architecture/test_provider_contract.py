"""Static contracts for the final typed provider and Application object graph."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SDK_PATH = ROOT / "nonebot_plugin_htmlrender" / "providers" / "sdk.py"
APPLICATION_PATH = ROOT / "nonebot_plugin_htmlrender" / "application" / "app.py"

EXPECTED_PROVIDER_DEPENDENCIES = frozenset(
    {
        "asset_publisher",
        "cache_observer",
        "operation_observer",
        "resources",
    }
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text("utf-8"), filename=str(path))


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} must be defined in the contracted module")


def _method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in class_node.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{class_node.name}.{name} must be defined")


def _field_names(class_node: ast.ClassDef) -> frozenset[str]:
    return frozenset(
        node.target.id
        for node in class_node.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    )


def _annotation_name(annotation: ast.expr | None) -> str | None:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    return None


def _argument_annotation(method: ast.FunctionDef, name: str) -> str | None:
    arguments = (*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs)
    for argument in arguments:
        if argument.arg == name:
            return _annotation_name(argument.annotation)
    raise AssertionError(f"{method.name} must accept {name}")


def _is_protocol_of_settings(base: ast.expr) -> bool:
    return (
        isinstance(base, ast.Subscript)
        and _annotation_name(base.value) == "Protocol"
        and _annotation_name(base.slice) == "SettingsT"
    )


def test_engine_provider_is_generic_over_one_typed_settings_flow() -> None:
    tree = _tree(SDK_PATH)
    provider = _class(tree, "EngineProvider")
    assert any(_is_protocol_of_settings(base) for base in provider.bases), (
        "EngineProvider must be declared as Protocol[SettingsT]"
    )

    typed_settings_methods = (
        "availability",
        "bootstrap_requirements",
        "compose",
        "resource_strategy",
    )
    for name in typed_settings_methods:
        method = _method(provider, name)
        assert _argument_annotation(method, "settings") == "SettingsT", (
            f"EngineProvider.{name} must consume SettingsT"
        )

    parse_settings = _method(provider, "parse_settings")
    assert _annotation_name(parse_settings.returns) == "SettingsT"
    resource_strategy = _method(provider, "resource_strategy")
    assert _annotation_name(resource_strategy.returns) == "ResourceStrategy"

    method_names = {
        node.name for node in provider.body if isinstance(node, ast.FunctionDef)
    }
    assert "resource_configuration" not in method_names, (
        "The transitional resource_configuration hook must not return"
    )


def test_provider_dtos_carry_the_final_resource_dependencies_and_strategy() -> None:
    tree = _tree(SDK_PATH)
    dependencies = _field_names(_class(tree, "ProviderDependencies"))
    bindings = _field_names(_class(tree, "EngineBindings"))

    assert dependencies == EXPECTED_PROVIDER_DEPENDENCIES, (
        "ProviderDependencies must expose only the provider-facing resource boundary"
    )
    assert "resource_strategy" not in bindings, (
        "ResourceStrategy must have one source of truth: "
        "EngineProvider.resource_strategy(), evaluated before composition"
    )
    assert {"description", "observation_attributes"}.isdisjoint(bindings), (
        "EngineBindings must not advertise metadata fields with no runtime contract"
    )


def test_application_exposes_preparation_and_resources_from_composition() -> None:
    application = _class(_tree(APPLICATION_PATH), "Application")
    initializer = _method(application, "__init__")
    parameters = {
        argument.arg
        for argument in (*initializer.args.args, *initializer.args.kwonlyargs)
    }
    assert {"preparation", "resources"} <= parameters

    properties = {
        node.name
        for node in application.body
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(decorator, ast.Name) and decorator.id == "property"
            for decorator in node.decorator_list
        )
    }
    assert {"preparation", "resources"} <= properties
