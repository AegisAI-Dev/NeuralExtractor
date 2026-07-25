"""Copy exact wheel-provided license and notice files into the release payload."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import re
import shutil
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "licenses" / "python"

# Runtime distributions found in the provider-free application closure. The
# final EXE scanner/inventory remains authoritative for what was collected.
EXPECTED_DISTRIBUTIONS = {
    "certifi": "2026.7.22",
    "charset-normalizer": "3.4.9",
    "defusedxml": "0.7.1",
    "idna": "3.18",
    "packaging": "26.2",
    "pillow": "12.3.0",
    "pyside6": "6.11.1",
    "pyside6-addons": "6.11.1",
    "pyside6-essentials": "6.11.1",
    "requests": "2.34.2",
    "setuptools": "83.0.0",
    "shiboken6": "6.11.1",
    "typing-extensions": "4.16.0",
    "urllib3": "2.7.0",
    "youtube-transcript-api": "1.2.4",
    "yt-dlp": "2026.7.4",
}
NOTICE_NAMES = ("license", "copying", "notice", "copyright", "authors")


def _safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def collect() -> list[Path]:
    copied: list[Path] = []
    for name, expected_version in sorted(EXPECTED_DISTRIBUTIONS.items()):
        distribution = importlib.metadata.distribution(name)
        if distribution.version != expected_version:
            raise RuntimeError(
                f"{name} version drift: expected {expected_version}, "
                f"found {distribution.version}"
            )
        notice_files = [
            file
            for file in distribution.files or ()
            if any(part in str(file).lower() for part in NOTICE_NAMES)
            and distribution.locate_file(file).is_file()
        ]
        if not notice_files:
            raise RuntimeError(f"{name} {expected_version} supplies no license/notice file")

        package_directory = OUTPUT_ROOT / (
            f"{_safe_component(name)}-{_safe_component(expected_version)}"
        )
        package_directory.mkdir(parents=True, exist_ok=True)
        for file in sorted(notice_files, key=str):
            source = Path(distribution.locate_file(file))
            relative = PurePosixPath(str(file).replace("\\", "/"))
            filename = "__".join(_safe_component(part) for part in relative.parts)
            destination = package_directory / filename
            shutil.copyfile(source, destination)
            copied.append(destination)

        metadata = package_directory / "WHEEL-METADATA.txt"
        license_expression = (
            distribution.metadata.get("License-Expression")
            or distribution.metadata.get("License")
            or "UNRESOLVED"
        )
        metadata.write_text(
            "\n".join(
                (
                    f"Name: {distribution.metadata.get('Name', name)}",
                    f"Version: {distribution.version}",
                    f"License expression/field: {license_expression}",
                    "Copied files:",
                    *(f"- {path.name} SHA-256 {_sha256(path)}" for path in copied if path.parent == package_directory),
                    "",
                )
            ),
            encoding="utf-8",
        )
        copied.append(metadata)
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    copied = collect()
    if args.check:
        print(f"Verified and refreshed {len(copied)} Python license/metadata files.")
    else:
        print(f"Collected {len(copied)} Python license/metadata files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
