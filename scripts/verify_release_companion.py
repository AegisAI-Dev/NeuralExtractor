"""Verify source and license companion manifests before a release is staged."""

from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from pathlib import Path, PurePosixPath

MANIFEST_LINE = re.compile(r"^([0-9a-fA-F]{64})[ \t]+\*?(.+?)\s*$")
SOURCE_REQUIRED = (
    "SOURCE-MANIFEST.sha256",
    "BUILDING.md",
    "INSTALLING-MODIFIED-LGPL-LIBRARIES.md",
)
LICENSE_MANIFEST = "RELEASE-LICENSE-MANIFEST.sha256"


def _sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/").removeprefix("./")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe manifest path: {value!r}")
    return path


def _parse_manifest(payload: str) -> dict[PurePosixPath, str]:
    records: dict[PurePosixPath, str] = {}
    for line_number, raw_line in enumerate(payload.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = MANIFEST_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"invalid manifest line {line_number}: {raw_line!r}")
        path = _safe_relative(match.group(2))
        if path in records:
            raise ValueError(f"duplicate manifest path: {path.as_posix()}")
        records[path] = match.group(1).lower()
    if not records:
        raise ValueError("manifest has no file records")
    return records


def verify_source_archive(archive_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            file_entries = [entry for entry in archive.infolist() if not entry.is_dir()]
            normalized_names = [entry.filename.replace("\\", "/") for entry in file_entries]
            if len(normalized_names) != len(set(normalized_names)):
                return ["source archive contains duplicate file names"]
            try:
                safe_names = [_safe_relative(name) for name in normalized_names]
            except ValueError as exc:
                return [str(exc)]
            entry_by_path = dict(zip(safe_names, file_entries, strict=True))
            manifests = [path for path in safe_names if path.name == SOURCE_REQUIRED[0]]
            if len(manifests) != 1:
                return ["source archive must contain exactly one SOURCE-MANIFEST.sha256"]
            manifest_path = manifests[0]
            source_root = manifest_path.parent
            required_paths = {source_root / name for name in SOURCE_REQUIRED}
            missing_required = sorted(required_paths - set(safe_names), key=str)
            if missing_required:
                errors.append(
                    "source archive is missing required files: "
                    + ", ".join(path.as_posix() for path in missing_required)
                )
            with archive.open(entry_by_path[manifest_path]) as stream:
                manifest = _parse_manifest(stream.read().decode("utf-8-sig"))
            listed_paths = {source_root / path for path in manifest}
            actual_paths = set(safe_names) - {manifest_path}
            if listed_paths != actual_paths:
                missing = sorted(actual_paths - listed_paths, key=str)
                extra = sorted(listed_paths - actual_paths, key=str)
                errors.append(
                    "source manifest coverage mismatch: "
                    f"unlisted={[path.as_posix() for path in missing]}, "
                    f"absent={[path.as_posix() for path in extra]}"
                )
            for relative_path, expected_hash in manifest.items():
                full_path = source_root / relative_path
                entry = entry_by_path.get(full_path)
                if entry is None:
                    continue
                if entry.file_size <= 0:
                    errors.append(f"source companion file is empty: {full_path.as_posix()}")
                    continue
                with archive.open(entry) as stream:
                    actual_hash = _sha256_stream(stream)
                if actual_hash != expected_hash:
                    errors.append(f"source companion hash mismatch: {full_path.as_posix()}")
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid source companion: {exc}")
    return errors


def verify_license_directory(license_root: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = license_root / LICENSE_MANIFEST
    if not manifest_path.is_file():
        return [f"license manifest is missing: {manifest_path}"]
    try:
        manifest = _parse_manifest(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"invalid license manifest: {exc}"]
    actual_paths = {
        PurePosixPath(path.relative_to(license_root).as_posix())
        for path in license_root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if set(manifest) != actual_paths:
        missing = sorted(actual_paths - set(manifest), key=str)
        extra = sorted(set(manifest) - actual_paths, key=str)
        errors.append(
            "license manifest coverage mismatch: "
            f"unlisted={[path.as_posix() for path in missing]}, "
            f"absent={[path.as_posix() for path in extra]}"
        )
    for relative_path, expected_hash in manifest.items():
        path = license_root.joinpath(*relative_path.parts)
        if not path.is_file():
            continue
        if path.stat().st_size <= 0:
            errors.append(f"license file is empty: {relative_path.as_posix()}")
            continue
        with path.open("rb") as stream:
            actual_hash = _sha256_stream(stream)
        if actual_hash != expected_hash:
            errors.append(f"license file hash mismatch: {relative_path.as_posix()}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--license-directory", type=Path, required=True)
    args = parser.parse_args()
    errors = verify_source_archive(args.source_archive.resolve())
    errors.extend(verify_license_directory(args.license_directory.resolve()))
    if errors:
        for error in errors:
            print(f"HOLD: {error}")
        return 1
    print("Corresponding-source and license manifests verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
