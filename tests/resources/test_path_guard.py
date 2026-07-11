from __future__ import annotations

import os
from pathlib import Path

import pytest

from nonebot_plugin_htmlrender.resources import path_guard
from nonebot_plugin_htmlrender.resources.path_guard import (
    is_subpath,
    sensitive_local_root,
    validate_local_access,
)


def _value_error(message: str) -> Exception:
    return ValueError(message)


@pytest.mark.parametrize(
    "relative",
    [
        Path(".ssh/id_ed25519"),
        Path(".aws/credentials"),
        Path(".gnupg/private-keys-v1.d/key"),
        Path(".kube/config"),
        Path(".docker/config.json"),
    ],
)
def test_user_secret_roots_are_blocked(
    relative: Path,
) -> None:
    candidate = Path.home() / relative

    assert sensitive_local_root(candidate) is not None


@pytest.mark.parametrize("name", [".env", ".env.production"])
def test_dotenv_names_are_blocked_anywhere(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="sensitive local path"):
        validate_local_access(
            tmp_path / "project" / name,
            allowed_roots=(),
            allow_any=True,
            on_deny=_value_error,
        )


def test_allowlist_uses_path_components_not_string_prefixes(tmp_path: Path) -> None:
    root = tmp_path / "etc"
    sibling = tmp_path / "etcfoo" / "asset.png"

    assert is_subpath(root, root)
    assert not is_subpath(sibling, root)
    with pytest.raises(ValueError, match="outside allowed roots"):
        validate_local_access(
            sibling,
            allowed_roots=(root,),
            allow_any=False,
            on_deny=_value_error,
        )
    assert (
        validate_local_access(
            root / "asset.png",
            allowed_roots=(root,),
            allow_any=False,
            on_deny=_value_error,
        )
        == (root / "asset.png").resolve()
    )


def test_allow_any_still_blocks_root_itself_and_descendants() -> None:
    sensitive = (Path.home() / ".ssh").resolve()

    for candidate in (sensitive, sensitive / "nested"):
        with pytest.raises(ValueError, match="sensitive local path"):
            validate_local_access(
                candidate,
                allowed_roots=(),
                allow_any=True,
                on_deny=_value_error,
            )


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only sensitive locations")
def test_posix_system_root_and_prefix_sibling() -> None:
    assert sensitive_local_root(Path("/etc")) == Path("/etc").resolve()
    assert sensitive_local_root(Path("/etc/passwd")) == Path("/etc").resolve()
    assert sensitive_local_root(Path("/etcfoo/passwd")) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_symlink_into_sensitive_root_is_blocked(tmp_path: Path) -> None:
    link = tmp_path / "system"
    link.symlink_to("/etc", target_is_directory=True)

    with pytest.raises(ValueError, match="sensitive local path"):
        validate_local_access(
            link / "passwd",
            allowed_roots=(),
            allow_any=True,
            on_deny=_value_error,
        )


def test_windows_sensitive_candidates_are_platform_complete() -> None:
    home = Path("C:/Users/Akashina")
    system_root = Path("C:/Windows")
    appdata = home / "AppData/Roaming"
    roots = path_guard._sensitive_root_candidates(
        platform="nt",
        home=home,
        environment={
            "SYSTEMROOT": str(system_root),
            "APPDATA": str(appdata),
        },
    )

    assert system_root / "System32/config/SAM" in roots
    assert system_root / "System32/config/SECURITY" in roots
    assert system_root / "System32/config/SYSTEM" in roots
    assert appdata / "gnupg" in roots
    assert appdata / "gcloud" in roots
    assert home / ".ssh" in roots


def test_empty_allowlist_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="without an allowed root"):
        validate_local_access(
            tmp_path / "asset.png",
            allowed_roots=(),
            allow_any=False,
            on_deny=_value_error,
        )
