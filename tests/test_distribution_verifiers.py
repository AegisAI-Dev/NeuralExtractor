from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from scripts import verify_distribution_boundary as boundary
from scripts import verify_packaged_licensing as packaged


class FakePyz:
    def __init__(self, modules: tuple[str, ...] = ("PySide6", "PySide6.QtCore")) -> None:
        self.payloads = {module: f"bytecode:{module}".encode() for module in modules}
        self.toc = {
            module: (0, index, len(self.payloads[module]))
            for index, module in enumerate(modules)
        }

    def extract(self, name: str, raw: bool = False) -> bytes:
        assert raw is True
        return self.payloads[name]


class FakeCArchive:
    def __init__(self, payloads: dict[str, bytes], pyz: FakePyz | None = None) -> None:
        self.payloads = payloads
        self.toc = {
            name: (0, len(payload), len(payload), 0, "b")
            for name, payload in payloads.items()
        }
        self.toc["PYZ.pyz"] = (0, 0, 0, 0, "z")
        self.pyz = pyz or FakePyz()

    def extract(self, name: str) -> bytes:
        return self.payloads[name]

    def open_embedded_archive(self, name: str) -> FakePyz:
        assert name == "PYZ.pyz"
        return self.pyz


def _valid_archive(monkeypatch: pytest.MonkeyPatch) -> FakeCArchive:
    ffi = b"audited CPython libffi fixture"
    ctypes_extension = b"audited CPython ctypes fixture"
    monkeypatch.setattr(packaged, "CPYTHON_LIBFFI_SHA256", hashlib.sha256(ffi).hexdigest())
    monkeypatch.setattr(
        packaged,
        "CPYTHON_CTYPES_SHA256",
        hashlib.sha256(ctypes_extension).hexdigest(),
    )
    license_payload = b"Example third-party license text\n"
    license_hash = hashlib.sha256(license_payload).hexdigest()
    manifest = f"{license_hash}  Example-LICENSE.txt\n".encode()
    payloads = {
        path.replace("/", "\\"): b"compliance\n"
        for path in packaged.REQUIRED_COMPLIANCE_PATHS
        if path != packaged.LICENSE_MANIFEST_PATH
    }
    payloads["SOURCE-HASHES.sha256"] = (
        f"{'0' * 64}  corresponding-source-only.txt\n".encode()
    )
    payloads.update(
        {
            packaged.LICENSE_MANIFEST_PATH.replace("/", "\\"): manifest,
            "licenses\\Example-LICENSE.txt": license_payload,
            "libffi-8.dll": ffi,
            "_ctypes.pyd": ctypes_extension,
        }
    )
    for path in packaged.REQUIRED_PYSIDE_PATHS:
        payloads[path.replace("/", "\\")] = f"fixture:{path}".encode()
    archive = FakeCArchive(payloads)
    normalized = {
        name: packaged._normalize_archive_path(name) for name in archive.toc
    }
    fingerprint = packaged._calculate_payload_fingerprint(archive, normalized)
    inventoried_paths = sorted(
        path
        for path in normalized.values()
        if path.casefold().endswith((".dll", ".pyd", ".exe"))
        or path.casefold().startswith(
            ("pyside6/plugins/", "pyside6/translations/")
        )
    )
    inventory_text = "\n".join(
        (
            "Public-distribution verdict: HOLD",
            "Release-gate-status: HOLD",
            "Qualified-review-status: HOLD",
            "Audit-blocker-count: 1",
            f"Audited non-compliance payload fingerprint SHA-256: {fingerprint}",
            "| PyQt code/binary/module | 0 | 0 | 0 |",
            "| bgutil/getpot/yt_dlp_plugins provider code/module | 0 | 0 | 0 |",
            "| Raw JavaScript/TypeScript payload | 0 | 0 | 0 |",
            "| canvas native/module payload | 0 | 0 | 0 |",
            *(f"| {path} | fixture |" for path in inventoried_paths),
            "",
        )
    ).encode()
    inventory_name = "THIRD_PARTY_LICENSES.txt"
    archive.payloads[inventory_name] = inventory_text
    return archive


def test_packaged_verifier_accepts_minimal_provider_free_pyside_archive(monkeypatch):
    archive = _valid_archive(monkeypatch)

    assert packaged.verify_archive(archive) == []


def test_packaged_verifier_accepts_consistent_reviewed_pass_status(monkeypatch):
    archive = _valid_archive(monkeypatch)
    inventory = archive.payloads["THIRD_PARTY_LICENSES.txt"]
    archive.payloads["THIRD_PARTY_LICENSES.txt"] = (
        inventory.replace(b"verdict: HOLD", b"verdict: PASS")
        .replace(b"status: HOLD", b"status: PASS")
        .replace(b"Audit-blocker-count: 1", b"Audit-blocker-count: 0")
    )

    assert packaged.verify_archive(archive) == []


def test_packaged_verifier_rejects_inconsistent_review_status(monkeypatch):
    archive = _valid_archive(monkeypatch)
    archive.payloads["THIRD_PARTY_LICENSES.txt"] = archive.payloads[
        "THIRD_PARTY_LICENSES.txt"
    ].replace(b"Release-gate-status: HOLD", b"Release-gate-status: PASS")

    errors = packaged.verify_archive(archive)

    assert any("inconsistent audit status" in error for error in errors)


@pytest.mark.parametrize(
    ("archive_path", "expected"),
    (
        ("PyQt6\\QtCore.pyd", "PyQt code or binary"),
        ("pyi_rth_pyqt6", "PyQt code or binary"),
        (
            "vendor\\bgutil-ytdlp-pot-provider\\LICENSE",
            "in-process provider code",
        ),
        ("payload\\generate_once.js", "raw JavaScript/TypeScript"),
        ("node_modules\\canvas\\build\\Release\\canvas.node", "canvas native"),
        ("canvas.node", "canvas native"),
        ("nested\\libffi-8.dll", "exactly one libffi DLL"),
        ("PySide6\\Qt6Pdf.dll", "unaudited PySide6/Qt paths"),
        ("PySide6\\plugins\\imageformats\\qpdf.dll", "unaudited PySide6/Qt paths"),
        ("PySide6\\translations\\qtbase_nl.qm", "unaudited PySide6/Qt paths"),
    ),
)
def test_packaged_verifier_rejects_forbidden_carchive_payloads(
    monkeypatch, archive_path, expected
):
    archive = _valid_archive(monkeypatch)
    archive.payloads[archive_path] = b"forbidden"
    archive.toc[archive_path] = (0, 1, 1, 0, "b")

    errors = packaged.verify_archive(archive)

    assert any(expected in error for error in errors)


@pytest.mark.parametrize(
    "module_name",
    (
        "PyQt6",
        "PyQt5.QtCore",
        "yt_dlp_plugins.extractor.getpot_bgutil",
        "getpot_bgutil",
    ),
)
def test_packaged_verifier_rejects_forbidden_pyz_modules(monkeypatch, module_name):
    archive = _valid_archive(monkeypatch)
    archive.pyz.payloads[module_name] = b"forbidden module bytecode"
    archive.pyz.toc[module_name] = (0, 0, len(archive.pyz.payloads[module_name]))

    errors = packaged.verify_archive(archive)

    assert any("forbidden in embedded PYZ" in error for error in errors)


def test_packaged_verifier_allows_yt_dlp_builtin_plugin_framework(monkeypatch):
    archive = _valid_archive(monkeypatch)
    module_name = "yt_dlp.plugins"
    archive.pyz.payloads[module_name] = b"builtin plugin framework bytecode"
    archive.pyz.toc[module_name] = (0, 0, len(archive.pyz.payloads[module_name]))

    normalized = {
        name: packaged._normalize_archive_path(name) for name in archive.toc
    }
    fingerprint = packaged._calculate_payload_fingerprint(archive, normalized)
    inventory_name = "THIRD_PARTY_LICENSES.txt"
    archive.payloads[inventory_name] = re.sub(
        rb"Audited non-compliance payload fingerprint SHA-256: [0-9a-f]{64}",
        f"Audited non-compliance payload fingerprint SHA-256: {fingerprint}".encode(),
        archive.payloads[inventory_name],
    )

    errors = packaged.verify_archive(archive)

    assert not any("provider module is forbidden" in error for error in errors)


def test_packaged_verifier_allows_historical_names_only_in_docs_and_licenses(monkeypatch):
    archive = _valid_archive(monkeypatch)
    notice = b"Historical PyQt6 and bgutil audit notice.\n"
    notice_hash = hashlib.sha256(notice).hexdigest()
    original_manifest_name = packaged.LICENSE_MANIFEST_PATH.replace("/", "\\")
    archive.payloads["licenses\\PyQt6-historical-notice.txt"] = notice
    archive.toc["licenses\\PyQt6-historical-notice.txt"] = (0, 1, 1, 0, "b")
    archive.payloads[original_manifest_name] += (
        f"{notice_hash}  PyQt6-historical-notice.txt\n".encode()
    )
    archive.payloads["docs\\bgutil-historical-audit.md"] = notice
    archive.toc["docs\\bgutil-historical-audit.md"] = (0, 1, 1, 0, "b")

    assert packaged.verify_archive(archive) == []


def test_packaged_verifier_requires_exact_single_root_libffi(monkeypatch):
    archive = _valid_archive(monkeypatch)
    archive.payloads["libffi-8.dll"] = b"wrong"

    errors = packaged.verify_archive(archive)

    assert any("archive hash mismatch for libffi-8.dll" in error for error in errors)


def test_packaged_verifier_requires_complete_hashed_license_manifest(monkeypatch):
    archive = _valid_archive(monkeypatch)
    archive.payloads["licenses\\unlisted.txt"] = b"missing from manifest"
    archive.toc["licenses\\unlisted.txt"] = (0, 1, 1, 0, "b")

    errors = packaged.verify_archive(archive)

    assert any("license manifest coverage mismatch" in error for error in errors)


def _write_valid_project(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text(
        "from PySide6.QtWidgets import QApplication\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        f"""[project]
name = "fixture"
version = "1.0.0"
dependencies = ["PySide6=={boundary.PYSIDE_VERSION}"]

[project.optional-dependencies]
build = ["pyinstaller==6.21.0"]
dev = ["pytest==9.1.1"]

[build-system]
requires = ["setuptools==83.0.0", "wheel==0.47.0"]
build-backend = "setuptools.build_meta"
""",
        encoding="utf-8",
    )
    (root / "requirements.txt").write_text(
        f"PySide6=={boundary.PYSIDE_VERSION}\npyinstaller==6.21.0\n",
        encoding="utf-8",
    )
    locked = "".join(
        f"{name}=={version} --hash=sha256:{'0' * 64}\n"
        for name, version in boundary._REQUIRED_LOCK_PACKAGES.items()
    )
    (root / "requirements.lock").write_text(locked, encoding="utf-8")
    uv_records = "\n".join(
        f"""[[package]]
name = "{name}"
version = "{version}"
source = {{ registry = "https://example.invalid/simple" }}
sdist = {{ url = "https://example.invalid/{name}.tar.gz", hash = "sha256:{'0' * 64}" }}
"""
        for name, version in boundary._REQUIRED_LOCK_PACKAGES.items()
    )
    (root / "uv.lock").write_text(f"version = 1\n{uv_records}", encoding="utf-8")

    compliance_lines = "\n".join(
        f'    project_root / "{path.name}",' for path in boundary.REQUIRED_COMPLIANCE_FILES
    )
    (root / "NeuralExtractorV3.spec").write_text(
        f'''project_root = Path.cwd()
python_libffi = Path(sys.base_prefix) / "DLLs" / "libffi-8.dll"
if (project_root / "vendor" / "bgutil-ytdlp-pot-provider").exists():
    raise SystemExit("forbidden")
require_sha256(python_libffi, "{boundary.CPYTHON_LIBFFI_SHA256}")
datas = [
{compliance_lines}
]
binaries = [(str(python_libffi), ".")]
a = Analysis(
    ["main.py"],
    pathex=[str(project_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    excludes=["PyQt", "PyQt5", "PyQt6", "yt_dlp_plugins", "bgutil_ytdlp_pot_provider"],
    noarchive=False,
)
''',
        encoding="utf-8",
    )
    for relative in boundary.REQUIRED_COMPLIANCE_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.name in {"SOURCE-HASHES.sha256", "requirements.lock"}:
            continue
        path.write_text(f"fixture compliance: {relative.as_posix()}\n", encoding="utf-8")
    source_payload = (root / "pyproject.toml").read_bytes()
    (root / "SOURCE-HASHES.sha256").write_text(
        f"{hashlib.sha256(source_payload).hexdigest()}  pyproject.toml\n",
        encoding="utf-8",
    )


def test_distribution_boundary_accepts_provider_free_exactly_locked_project(tmp_path):
    _write_valid_project(tmp_path)
    (tmp_path / "docs" / "OPTIONAL-PO-PROVIDER.md").write_text(
        "Historical PyQt6, bgutil, getpot, and yt_dlp_plugins names are documentation.\n",
        encoding="utf-8",
    )

    assert boundary.verify_project(tmp_path) == []


def test_distribution_boundary_rejects_pyqt_import(tmp_path):
    _write_valid_project(tmp_path)
    (tmp_path / "src" / "app.py").write_text(
        "from PyQt6.QtWidgets import QApplication\n", encoding="utf-8"
    )

    assert any("forbidden in-process import" in error for error in boundary.verify_project(tmp_path))


def test_distribution_boundary_rejects_dynamic_provider_import(tmp_path):
    _write_valid_project(tmp_path)
    (tmp_path / "src" / "app.py").write_text(
        'import importlib\nimportlib.import_module("yt_dlp_plugins.extractor.getpot_bgutil")\n',
        encoding="utf-8",
    )

    assert any("forbidden dynamic import" in error for error in boundary.verify_project(tmp_path))


def test_distribution_boundary_rejects_structured_dependency_but_not_comment(tmp_path):
    _write_valid_project(tmp_path)
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        requirements.read_text(encoding="utf-8")
        + "# historical bgutil-ytdlp-pot-provider and PyQt6 note\n"
        + "bgutil-ytdlp-pot-provider==1.3.1\n",
        encoding="utf-8",
    )

    errors = boundary.verify_project(tmp_path)

    assert any("forbidden dependency in requirements.txt" in error for error in errors)
    assert sum("forbidden dependency in requirements.txt" in error for error in errors) == 1


def test_distribution_boundary_rejects_provider_tree_and_spec_payload(tmp_path):
    _write_valid_project(tmp_path)
    provider_root = tmp_path / boundary.PROVIDER_VENDOR_PATH
    provider_root.mkdir(parents=True)
    spec = tmp_path / "NeuralExtractorV3.spec"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace(
            "hiddenimports=[]", 'hiddenimports=["yt_dlp_plugins.extractor.getpot_bgutil"]'
        ),
        encoding="utf-8",
    )

    errors = boundary.verify_project(tmp_path)

    assert any("GPL provider tree is present" in error for error in errors)
    assert any("spec hiddenimports references forbidden payloads" in error for error in errors)


def test_distribution_boundary_rejects_source_hash_mismatch(tmp_path):
    _write_valid_project(tmp_path)
    (tmp_path / "pyproject.toml").write_text("changed\n", encoding="utf-8")

    errors = boundary.verify_project(tmp_path)

    assert any("source-hash mismatch: pyproject.toml" in error for error in errors)
