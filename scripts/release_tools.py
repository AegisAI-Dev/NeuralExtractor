"""Validate V3 release versions and generate the strict release manifest."""

from __future__ import annotations

import argparse
import ast
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from neural_extractor_v3.core.update_manifest import (  # noqa: E402
    UpdateManifest,
    UpdateValidationError,
    expected_manifest_filename,
    parse_numeric_version,
)

BOOTSTRAP_UPDATER_VERSION = "3.0.2"


def config_version(project_root: Path) -> str:
    config_path = project_root / "src" / "neural_extractor_v3" / "config.py"
    tree = ast.parse(config_path.read_text(encoding="utf-8"), filename=str(config_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    raise ValueError("VERSION was not found as a string constant in config.py")


def project_version(project_root: Path) -> str:
    payload = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    value = payload.get("project", {}).get("version")
    if not isinstance(value, str):
        raise ValueError("project.version is missing from pyproject.toml")
    return value


def release_version(release_ref: str) -> str:
    value = str(release_ref or "")
    version = value[1:] if value.startswith("v") else value
    parse_numeric_version(version)
    return version


def validate_release_versions(project_root: Path, release_ref: str) -> str:
    release = release_version(release_ref)
    config = config_version(project_root)
    project = project_version(project_root)
    parse_numeric_version(config)
    parse_numeric_version(project)
    if config != project:
        raise ValueError(
            f"Version mismatch: config.py={config}, pyproject.toml={project}"
        )
    if release != config:
        raise ValueError(
            f"Release version mismatch: release={release}, source={config}"
        )
    return release


def generate_manifest(
    *,
    version: str,
    executable: Path,
    output: Path,
    minimum_updater_version: str = BOOTSTRAP_UPDATER_VERSION,
) -> UpdateManifest:
    parse_numeric_version(version)
    parse_numeric_version(minimum_updater_version)
    expected_output = expected_manifest_filename(version)
    if output.name != expected_output:
        raise ValueError(f"Manifest output must be named {expected_output}")
    manifest = UpdateManifest.for_executable(
        version=version,
        executable=executable,
        minimum_updater_version=minimum_updater_version,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(manifest.to_json(), encoding="utf-8", newline="\n")
    return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate release/source versions")
    validate.add_argument("--release-ref", required=True)
    validate.add_argument("--project-root", type=Path, default=PROJECT_ROOT)

    manifest = subparsers.add_parser("manifest", help="Generate strict release manifest")
    manifest.add_argument("--version", required=True)
    manifest.add_argument("--exe", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument(
        "--minimum-updater-version",
        default=BOOTSTRAP_UPDATER_VERSION,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            version = validate_release_versions(args.project_root.resolve(), args.release_ref)
            print(f"Release version validated: {version}")
        else:
            manifest = generate_manifest(
                version=args.version,
                executable=args.exe.resolve(),
                output=args.output.resolve(),
                minimum_updater_version=args.minimum_updater_version,
            )
            print(
                f"Manifest generated: {args.output.name} "
                f"({manifest.asset_size} bytes, sha256={manifest.asset_sha256})"
            )
    except (OSError, ValueError, UpdateValidationError) as exc:
        print(f"Release validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
