#!/usr/bin/env python3
"""Verify built distributions and exercise them outside the source tree."""

from __future__ import annotations

import argparse
from base64 import urlsafe_b64encode
import csv
from email import message_from_bytes
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Final
import zipfile

if TYPE_CHECKING:
    from email.message import Message

PACKAGE_NAME: Final = "nonebot-plugin-htmlrender"
PACKAGE_IMPORT: Final = "nonebot_plugin_htmlrender"
TAKUMI_VERSION: Final = "0.2.0"
REQUIRES_PYTHON_FORMS: Final = frozenset({">=3.10,<4.0", "<4.0,>=3.10"})
PACKAGE_RESOURCES: Final = (
    "nonebot_plugin_htmlrender/templates/markdown/github-markdown-light.css",
    "nonebot_plugin_htmlrender/templates/markdown/markdown.html",
    "nonebot_plugin_htmlrender/templates/markdown/pygments-default.css",
    "nonebot_plugin_htmlrender/templates/markdown/katex/katex.min.b64_fonts.css",
    "nonebot_plugin_htmlrender/templates/markdown/katex/katex.min.js",
    "nonebot_plugin_htmlrender/templates/markdown/katex/mathtex-script-type.min.js",
    "nonebot_plugin_htmlrender/templates/markdown/katex/mhchem.min.js",
    "nonebot_plugin_htmlrender/templates/text/text.css",
    "nonebot_plugin_htmlrender/templates/text/text.html",
)

_BASE_SMOKE = r"""
import asyncio
from importlib.metadata import version
from importlib.resources import files
import json
import os
from pathlib import Path, PurePosixPath

import nonebot

expected_version = os.environ["HTMLRENDER_EXPECTED_VERSION"]
expected_resources = json.loads(os.environ["HTMLRENDER_EXPECTED_RESOURCES"])
repository_root = Path(os.environ["HTMLRENDER_REPOSITORY_ROOT"]).resolve()


def check(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


nonebot.init(driver="~none", render={"provider": None})
plugin = nonebot.load_plugin("nonebot_plugin_htmlrender")
check(plugin is not None, "NoneBot could not load nonebot_plugin_htmlrender")

import nonebot_plugin_htmlrender
from nonebot_plugin_htmlrender.preparation import prepare_markdown, prepare_text

module_path = Path(nonebot_plugin_htmlrender.__file__).resolve()
check(
    not module_path.is_relative_to(repository_root),
    f"Smoke imported the source checkout instead of the installed wheel: {module_path}",
)
installed_version = version("nonebot-plugin-htmlrender")
check(
    installed_version == expected_version,
    f"Installed version {installed_version!r} != expected {expected_version!r}",
)

package_root = files("nonebot_plugin_htmlrender")
for resource_name in expected_resources:
    relative = PurePosixPath(resource_name).relative_to("nonebot_plugin_htmlrender")
    resource = package_root.joinpath(*relative.parts)
    check(resource.is_file(), f"Installed package resource is missing: {resource_name}")
    check(
        bool(resource.read_bytes()),
        f"Installed package resource is empty: {resource_name}",
    )


async def main() -> None:
    text = await prepare_text("wheel <smoke> & Unicode 字符")
    check(
        "wheel &lt;smoke&gt; &amp; Unicode 字符" in text.html,
        "Installed text preparation did not preserve escaping and Unicode",
    )

    markdown = await prepare_markdown("# wheel smoke\n\n$$x^2$$")
    check(
        "<h1>wheel smoke</h1>" in markdown.html,
        "Installed Markdown preparation did not render ordinary Markdown",
    )
    check(
        "<script defer>" in markdown.html,
        "Installed Markdown preparation did not load the math scripts",
    )
    check(
        ".katex" in markdown.html,
        "Installed Markdown preparation did not load the KaTeX stylesheet",
    )


asyncio.run(main())
"""

_TAKUMI_SMOKE = r"""
import asyncio
from importlib.metadata import version
import os
import struct

import nonebot


def check(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


nonebot.init(driver="~none", render={"provider": "takumi", "startup": "off"})
plugin = nonebot.load_plugin("nonebot_plugin_htmlrender")
check(plugin is not None, "NoneBot could not load nonebot_plugin_htmlrender")

from nonebot_plugin_htmlrender.adapters.takumi import TakumiConfig, TakumiExtension
from nonebot_plugin_htmlrender.adapters.takumi.operations import rasterize_html
from nonebot_plugin_htmlrender.adapters.takumi.runtime import create_runtime_state
from nonebot_plugin_htmlrender.preparation import RasterOptions, prepare_text

installed_version = version("nonebot-plugin-htmlrender")
expected_version = os.environ["HTMLRENDER_EXPECTED_VERSION"]
check(
    installed_version == expected_version,
    f"Installed version {installed_version!r} != expected {expected_version!r}",
)
installed_takumi_version = version("takumi-py")
expected_takumi_version = os.environ["HTMLRENDER_EXPECTED_TAKUMI_VERSION"]
check(
    installed_takumi_version == expected_takumi_version,
    "Installed takumi-py version "
    f"{installed_takumi_version!r} != expected {expected_takumi_version!r}",
)


async def main() -> None:
    state = await create_runtime_state(TakumiConfig())
    try:
        node = {
            "type": "container",
            "style": {
                "width": 8,
                "height": 4,
                "backgroundColor": "#ff0000",
            },
        }
        rendered = await TakumiExtension(state).render_node(node, width=8, height=4)
        check(
            rendered.startswith(b"\x89PNG\r\n\x1a\n"),
            "Takumi node smoke did not produce a PNG",
        )
        dimensions = struct.unpack(">II", rendered[16:24])
        check(
            dimensions == (8, 4),
            f"Takumi node smoke produced unexpected dimensions: {dimensions!r}",
        )

        prepared_text = await prepare_text("installed Takumi smoke")
        prepared = await rasterize_html(
            state,
            prepared_text,
            RasterOptions(width=180, device_pixel_ratio=1.0),
        )
        check(
            prepared.startswith(b"\x89PNG\r\n\x1a\n"),
            "Takumi installed text smoke did not produce a PNG",
        )
    finally:
        await state.aclose()


asyncio.run(main())
"""


class DistributionVerificationError(RuntimeError):
    """A built artifact does not satisfy the release contract."""


def _log(message: str) -> None:
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()


def _normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _only_artifact(paths: list[Path], kind: str) -> Path:
    if len(paths) != 1:
        found = ", ".join(sorted(path.name for path in paths)) or "none"
        raise DistributionVerificationError(
            f"Expected exactly one {kind}, found {len(paths)}: {found}."
        )
    return paths[0]


def _read_archive_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    file = archive.extractfile(member)
    if file is None:
        raise DistributionVerificationError(
            f"Could not read source distribution member {member.name!r}."
        )
    return file.read()


def _validate_metadata(
    metadata: Message,
    *,
    expected_version: str,
    artifact: Path,
) -> None:
    name = metadata.get("Name")
    if name is None or _normalize_distribution_name(name) != PACKAGE_NAME:
        raise DistributionVerificationError(
            f"{artifact.name} has unexpected project name {name!r}."
        )

    version = metadata.get("Version")
    if version != expected_version:
        raise DistributionVerificationError(
            f"{artifact.name} has version {version!r}, expected {expected_version!r}."
        )

    requires_python = metadata.get("Requires-Python")
    if requires_python is None:
        raise DistributionVerificationError(
            f"{artifact.name} does not declare Requires-Python."
        )
    if requires_python.replace(" ", "") not in REQUIRES_PYTHON_FORMS:
        raise DistributionVerificationError(
            f"{artifact.name} has unexpected Requires-Python {requires_python!r}."
        )

    extras = set(metadata.get_all("Provides-Extra", []))
    if "takumi" not in extras:
        raise DistributionVerificationError(
            f"{artifact.name} does not provide the 'takumi' extra."
        )

    normalized_requirements = {
        requirement.lower().replace(" ", "").replace('"', "'")
        for requirement in metadata.get_all("Requires-Dist", [])
    }
    expected_requirement = f"takumi-py=={TAKUMI_VERSION};extra=='takumi'"
    if expected_requirement not in normalized_requirements:
        raise DistributionVerificationError(
            f"{artifact.name} does not require the exact Takumi extra "
            f"{expected_requirement!r}."
        )


def _verify_record_entry(
    path: str, data: bytes, record: dict[str, tuple[str, str]]
) -> None:
    entry = record.get(path)
    if entry is None:
        raise DistributionVerificationError(f"Wheel RECORD does not contain {path!r}.")

    digest, size = entry
    expected_digest = "sha256=" + urlsafe_b64encode(
        sha256(data).digest()
    ).decode().rstrip("=")
    if digest != expected_digest:
        raise DistributionVerificationError(
            f"Wheel RECORD digest mismatch for {path!r}."
        )
    if size != str(len(data)):
        raise DistributionVerificationError(
            f"Wheel RECORD size mismatch for {path!r}: {size!r}."
        )


def _verify_wheel(
    wheel: Path,
    *,
    expected_version: str,
) -> dict[str, bytes]:
    with zipfile.ZipFile(wheel) as archive:
        corrupt_member = archive.testzip()
        if corrupt_member is not None:
            raise DistributionVerificationError(
                f"Wheel contains a corrupt member: {corrupt_member!r}."
            )
        names = archive.namelist()
        metadata_path = _only_artifact(
            [Path(name) for name in names if name.endswith(".dist-info/METADATA")],
            "wheel METADATA file",
        ).as_posix()
        record_path = _only_artifact(
            [Path(name) for name in names if name.endswith(".dist-info/RECORD")],
            "wheel RECORD file",
        ).as_posix()
        metadata = message_from_bytes(archive.read(metadata_path))
        _validate_metadata(
            metadata,
            expected_version=expected_version,
            artifact=wheel,
        )

        record_rows = csv.reader(archive.read(record_path).decode("utf-8").splitlines())
        record = {row[0]: (row[1], row[2]) for row in record_rows if len(row) == 3}
        packaged_resources = {
            name
            for name in names
            if name.startswith(f"{PACKAGE_IMPORT}/templates/")
            and not name.endswith("/")
        }
        expected_resources = set(PACKAGE_RESOURCES)
        if packaged_resources != expected_resources:
            raise DistributionVerificationError(
                "Wheel package resource manifest mismatch: "
                f"missing={sorted(expected_resources - packaged_resources)}, "
                f"unexpected={sorted(packaged_resources - expected_resources)}."
            )
        resources: dict[str, bytes] = {}
        for resource_name in PACKAGE_RESOURCES:
            resource_count = names.count(resource_name)
            if resource_count != 1:
                raise DistributionVerificationError(
                    f"Wheel expected one package resource {resource_name!r}, "
                    f"found {resource_count}."
                )
            data = archive.read(resource_name)
            if not data:
                raise DistributionVerificationError(
                    f"Wheel package resource {resource_name!r} is empty."
                )
            _verify_record_entry(resource_name, data, record)
            resources[resource_name] = data
        return resources


def _verify_sdist(
    sdist: Path,
    *,
    expected_version: str,
    wheel_resources: dict[str, bytes],
) -> None:
    with tarfile.open(sdist, mode="r:gz") as archive:
        members = archive.getmembers()
        packaged_resources = {
            member.name[member.name.index(f"/{PACKAGE_IMPORT}/") + 1 :]
            for member in members
            if member.isfile() and f"/{PACKAGE_IMPORT}/templates/" in member.name
        }
        expected_resources = set(PACKAGE_RESOURCES)
        if packaged_resources != expected_resources:
            raise DistributionVerificationError(
                "Source distribution package resource manifest mismatch: "
                f"missing={sorted(expected_resources - packaged_resources)}, "
                f"unexpected={sorted(packaged_resources - expected_resources)}."
            )
        metadata_member = _only_artifact(
            [
                Path(member.name)
                for member in members
                if member.name.endswith("/PKG-INFO")
            ],
            "source distribution PKG-INFO file",
        ).as_posix()
        metadata_info = archive.getmember(metadata_member)
        metadata = message_from_bytes(_read_archive_member(archive, metadata_info))
        _validate_metadata(
            metadata,
            expected_version=expected_version,
            artifact=sdist,
        )

        for resource_name in PACKAGE_RESOURCES:
            suffix = f"/{resource_name}"
            matching = [
                member
                for member in members
                if member.isfile() and member.name.endswith(suffix)
            ]
            if len(matching) != 1:
                raise DistributionVerificationError(
                    f"Source distribution expected one {resource_name!r}, "
                    f"found {len(matching)}."
                )
            data = _read_archive_member(archive, matching[0])
            if data != wheel_resources[resource_name]:
                raise DistributionVerificationError(
                    f"Wheel and source distribution disagree for {resource_name!r}."
                )


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _run(command: list[str], *, cwd: Path, env: dict[str, str], label: str) -> None:
    _log(f"==> {label}")
    try:
        subprocess.run(command, cwd=cwd, env=env, check=True)  # noqa: S603
    except subprocess.CalledProcessError as error:
        raise DistributionVerificationError(
            f"{label} failed with exit code {error.returncode}."
        ) from error


def _create_venv(
    root: Path,
    *,
    name: str,
    python_version: str,
    uv: str,
    env: dict[str, str],
) -> tuple[Path, Path]:
    venv = root / name
    run_dir = root / f"{name}-run"
    run_dir.mkdir()
    _run(
        [uv, "venv", "--python", python_version, str(venv)],
        cwd=run_dir,
        env=env,
        label=f"Create isolated {name} environment",
    )
    return _venv_python(venv), run_dir


def _install_artifact(
    python: Path,
    artifact: str,
    *,
    uv: str,
    cwd: Path,
    env: dict[str, str],
    label: str,
) -> None:
    _run(
        [uv, "pip", "install", "--python", str(python), artifact],
        cwd=cwd,
        env=env,
        label=label,
    )


def _run_install_smokes(
    wheel: Path,
    sdist: Path,
    *,
    expected_version: str,
    python_version: str,
    uv: str,
    repository_root: Path,
    smoke_sdist: bool,
) -> None:
    with TemporaryDirectory(prefix="htmlrender-dist-smoke-") as temporary:
        root = Path(temporary).resolve()
        env = os.environ.copy()
        for inherited_name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
            env.pop(inherited_name, None)
        env.update(
            {
                "HOME": str(root / "home"),
                "HTMLRENDER_EXPECTED_RESOURCES": json.dumps(PACKAGE_RESOURCES),
                "HTMLRENDER_EXPECTED_TAKUMI_VERSION": TAKUMI_VERSION,
                "HTMLRENDER_EXPECTED_VERSION": expected_version,
                "HTMLRENDER_REPOSITORY_ROOT": str(repository_root),
                "PYTHONNOUSERSITE": "1",
                "UV_NO_PROGRESS": "1",
                "XDG_CACHE_HOME": str(root / "xdg-cache"),
                "XDG_CONFIG_HOME": str(root / "xdg-config"),
                "XDG_DATA_HOME": str(root / "xdg-data"),
            }
        )

        wheel_python, wheel_run_dir = _create_venv(
            root,
            name="wheel",
            python_version=python_version,
            uv=uv,
            env=env,
        )
        _install_artifact(
            wheel_python,
            str(wheel.resolve()),
            uv=uv,
            cwd=wheel_run_dir,
            env=env,
            label="Install wheel with core dependencies",
        )
        _run(
            [str(wheel_python), "-c", _BASE_SMOKE],
            cwd=wheel_run_dir,
            env=env,
            label="Run installed-wheel package resource and preparation smoke",
        )

        _install_artifact(
            wheel_python,
            f"{wheel.resolve()}[takumi]",
            uv=uv,
            cwd=wheel_run_dir,
            env=env,
            label="Install wheel Takumi extra",
        )
        _run(
            [str(wheel_python), "-c", _TAKUMI_SMOKE],
            cwd=wheel_run_dir,
            env=env,
            label="Run installed-wheel Takumi native smoke",
        )

        if smoke_sdist:
            sdist_python, sdist_run_dir = _create_venv(
                root,
                name="sdist",
                python_version=python_version,
                uv=uv,
                env=env,
            )
            _install_artifact(
                sdist_python,
                str(sdist.resolve()),
                uv=uv,
                cwd=sdist_run_dir,
                env=env,
                label="Build and install source distribution",
            )
            _run(
                [str(sdist_python), "-c", _BASE_SMOKE],
                cwd=sdist_run_dir,
                env=env,
                label="Run installed-sdist package resource and preparation smoke",
            )
            _install_artifact(
                sdist_python,
                f"{sdist.resolve()}[takumi]",
                uv=uv,
                cwd=sdist_run_dir,
                env=env,
                label="Install source distribution Takumi extra",
            )
            _run(
                [str(sdist_python), "-c", _TAKUMI_SMOKE],
                cwd=sdist_run_dir,
                env=env,
                label="Run installed-sdist Takumi native smoke",
            )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dist_dir",
        nargs="?",
        default=Path("dist"),
        type=Path,
        help="Directory containing exactly one wheel and one .tar.gz sdist.",
    )
    parser.add_argument(
        "--expected-version",
        required=True,
        help="Version required in both distribution metadata files.",
    )
    parser.add_argument(
        "--python",
        default="3.12",
        help="Python version used by isolated smoke environments.",
    )
    parser.add_argument(
        "--uv",
        default=os.environ.get("UV", "uv"),
        help="uv executable used to create isolated environments.",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Validate archives without installing them.",
    )
    parser.add_argument(
        "--wheel-only-smoke",
        action="store_true",
        help="Install and smoke the wheel, but skip the source distribution install.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    dist_dir = args.dist_dir.expanduser().resolve()
    if not dist_dir.is_dir():
        raise DistributionVerificationError(
            f"Distribution directory does not exist: {dist_dir}."
        )

    wheel = _only_artifact(list(dist_dir.glob("*.whl")), "wheel")
    sdist = _only_artifact(list(dist_dir.glob("*.tar.gz")), "source distribution")
    _log(f"==> Verify archive metadata and package resources in {dist_dir}")
    wheel_resources = _verify_wheel(
        wheel,
        expected_version=args.expected_version,
    )
    _verify_sdist(
        sdist,
        expected_version=args.expected_version,
        wheel_resources=wheel_resources,
    )

    if not args.metadata_only:
        _run_install_smokes(
            wheel,
            sdist,
            expected_version=args.expected_version,
            python_version=args.python,
            uv=args.uv,
            repository_root=Path(__file__).resolve().parents[1],
            smoke_sdist=not args.wheel_only_smoke,
        )
    _log("Distribution verification passed.")


if __name__ == "__main__":
    try:
        main()
    except DistributionVerificationError as error:
        sys.stderr.write(f"Distribution verification failed: {error}\n")
        raise SystemExit(1) from None
