"""Contracts shared by release and distribution verification workflows."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SKIA_ACTION = ROOT / ".github" / "actions" / "setup-skia-runtime" / "action.yml"
SKIA_SETUP = "uses: ./.github/actions/setup-skia-runtime"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_skia_runtime_action_owns_linux_dependencies() -> None:
    action = SKIA_ACTION.read_text(encoding="utf-8")

    assert "using: composite" in action
    for package in ("libegl1", "libexpat1", "libgl1"):
        assert package in action

    for workflow in WORKFLOWS.glob("*.yml"):
        assert "sudo apt-get install" not in workflow.read_text(encoding="utf-8")


def test_all_skia_smoke_workflows_use_shared_runtime_setup() -> None:
    expected_uses = {
        "auto-tag.yml": 1,
        "ci.yml": 2,
        "coverage.yml": 1,
        "publish-test.yml": 1,
        "publish.yml": 1,
    }

    for workflow, count in expected_uses.items():
        assert _workflow(workflow).count(SKIA_SETUP) == count


def test_distribution_preflight_installs_skia_runtime_first() -> None:
    for workflow in ("auto-tag.yml", "ci.yml", "publish-test.yml", "publish.yml"):
        content = _workflow(workflow)
        assert "make verify-artifacts" in content
        assert content.index(SKIA_SETUP) < content.index("make verify-artifacts")


def test_pre_tag_recovery_preserves_release_gates() -> None:
    workflow = _workflow("auto-tag.yml")
    docs_trigger = _workflow("docs.yml").partition("permissions:")[0]

    assert "workflow_dispatch:" in workflow
    assert "source_sha:" in workflow
    assert '"${SOURCE_SHA}" != "${MASTER_SHA}"' in workflow
    assert "Tag ${TAG} already exists; recover with Publish instead." in workflow
    assert "paths:" not in docs_trigger
    for required in (
        "CI:ci.yml",
        "Coverage:coverage.yml",
        "Docs:docs.yml",
        "Prek:prek.yml",
    ):
        assert required in workflow
