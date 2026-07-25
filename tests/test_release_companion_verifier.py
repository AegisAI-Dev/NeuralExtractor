import hashlib
import zipfile
from pathlib import Path

from scripts.verify_release_companion import (
    LICENSE_MANIFEST,
    verify_license_directory,
    verify_source_archive,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_source_companion_requires_complete_matching_manifest(tmp_path: Path):
    archive_path = tmp_path / "source.zip"
    files = {
        "BUILDING.md": b"build instructions\n",
        "INSTALLING-MODIFIED-LGPL-LIBRARIES.md": b"relink instructions\n",
        "src/app.py": b"print('ok')\n",
    }
    manifest = "".join(
        f"{_sha256(payload)}  {name}\n" for name, payload in sorted(files.items())
    )
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, payload in files.items():
            archive.writestr(f"companion/{name}", payload)
        archive.writestr("companion/SOURCE-MANIFEST.sha256", manifest)

    assert verify_source_archive(archive_path) == []

    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr("companion/unlisted.txt", b"not in manifest\n")
    assert any("coverage mismatch" in error for error in verify_source_archive(archive_path))


def test_license_directory_manifest_rejects_tampering(tmp_path: Path):
    license_root = tmp_path / "licenses"
    license_root.mkdir()
    license_file = license_root / "component-LICENSE.txt"
    license_file.write_text("exact license text\n", encoding="utf-8")
    digest = hashlib.sha256(license_file.read_bytes()).hexdigest()
    (license_root / LICENSE_MANIFEST).write_text(
        f"{digest}  component-LICENSE.txt\n", encoding="utf-8"
    )

    assert verify_license_directory(license_root) == []

    license_file.write_text("tampered\n", encoding="utf-8")
    assert any("hash mismatch" in error for error in verify_license_directory(license_root))
