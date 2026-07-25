from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from scripts import generate_distribution_inventory as inventory


class FakePyz:
    def __init__(self, modules: tuple[str, ...]) -> None:
        self.payloads = {name: f"bytecode:{name}".encode() for name in modules}
        self.toc = {
            name: (0, index, len(self.payloads[name]))
            for index, name in enumerate(modules)
        }

    def extract(self, name: str, raw: bool = False) -> bytes:
        assert raw is True
        return self.payloads[name]


class FakeCArchive:
    def __init__(
        self,
        payloads: dict[str, bytes],
        *,
        modules: tuple[str, ...] = (
            "PySide6",
            "PySide6.QtCore",
            "PIL",
            "requests",
            "requests.sessions",
            "yt_dlp",
        ),
        pyz_count: int = 1,
    ) -> None:
        self.payloads = payloads
        self.toc = {
            name: (0, len(payload), len(payload), 0, "b") for name, payload in payloads.items()
        }
        for index in range(pyz_count):
            name = "PYZ.pyz" if index == 0 else f"PYZ-{index}.pyz"
            self.toc[name] = (0, 0, 0, 0, "z")
        self.pyz = FakePyz(modules)

    def extract(self, name: str) -> bytes:
        return self.payloads[name]

    def open_embedded_archive(self, name: str) -> FakePyz:
        assert name.startswith("PYZ")
        return self.pyz


def _fixture_archive() -> FakeCArchive:
    lock = b"""pyside6==6.11.1 \\\n+    --hash=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \\\n+    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
requests==2.34.2 \\\n+    --hash=sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
"""
    payloads = {
        path.replace("/", "\\"): b"compliance\n"
        for path in inventory.COMPLIANCE_PATHS
        if path != "requirements.lock"
    }
    payloads.update(
        {
            "requirements.lock": lock,
            "libffi-8.dll": b"ffi",
            "python312.dll": b"python",
            "PySide6\\QtCore.pyd": b"qt-core-binding",
            "PySide6\\Qt6Core.dll": b"qt-core",
            "PySide6\\plugins\\platforms\\qwindows.dll": b"qt-platform",
            "PySide6\\translations\\qtbase_en.qm": b"translation",
            "PIL\\_imaging.pyd": b"pillow-native",
            "bin\\node.exe": b"node",
            "bin\\ffmpeg.exe": b"ffmpeg",
        }
    )
    return FakeCArchive(payloads)


def test_render_inventory_is_deterministic_and_covers_exact_binary_tables(tmp_path):
    executable = tmp_path / "app.exe"
    executable.write_bytes(b"outer artifact bytes")
    archive = _fixture_archive()

    first = inventory.render_inventory(executable, archive)
    second = inventory.render_inventory(executable, archive)

    assert first == second
    assert "Status: HOLD - NOT APPROVED FOR PUBLIC DISTRIBUTION" in first
    assert hashlib.sha256(executable.read_bytes()).hexdigest() in first
    assert "| PyQt code/binary/module | 0 | 0 | 0 |" in first
    assert "| bgutil/getpot/yt_dlp_plugins provider code/module | 0 | 0 | 0 |" in first
    assert "| Raw JavaScript/TypeScript payload | 0 | 0 | 0 |" in first
    assert "| canvas native/module payload | 0 | 0 | 0 |" in first
    assert "libffi DLL count: 1" in first
    assert "PySide6/plugins/platforms/qwindows.dll" in first
    assert "PySide6/translations/qtbase_en.qm" in first
    assert "PIL/_imaging.pyd" in first
    assert "bin/node.exe" in first
    assert "bgutil-ytdlp-pot-provider optional helper" in first
    assert "EXTERNAL / NOT INCLUDED" in first

    # Lock hashes are sorted, independently of their source-file order.
    assert first.index("a" * 64) < first.index("b" * 64)
    # Native files appear in exactly one of the two native partitions.
    assert first.count("PIL/_imaging.pyd") == 1
    assert first.count("PySide6/QtCore.pyd") == 1


def test_embeddable_inventory_marks_self_referential_hashes(tmp_path):
    executable = tmp_path / "app.exe"
    executable.write_bytes(b"outer artifact bytes")
    archive = _fixture_archive()

    report = inventory.render_inventory(
        executable,
        archive,
        include_outer_identity=False,
    )

    assert (
        "| THIRD_PARTY_LICENSES.txt | YES | SELF-REFERENTIAL | "
        "SEE POST-BUILD SIDECAR |"
    ) in report
    assert (
        "| SOURCE-HASHES.sha256 | YES | SELF-REFERENTIAL | "
        "SEE POST-BUILD SIDECAR |"
    ) in report
    assert (
        "| LICENSE | YES | FINAL-BUILD-DEPENDENT | SEE POST-BUILD SIDECAR |"
    ) in report
    assert "Artifact SHA-256: OMITTED FROM EMBEDDED REPORT" in report


def test_inventory_fingerprint_changes_when_pyz_bytecode_changes(tmp_path):
    executable = tmp_path / "app.exe"
    executable.write_bytes(b"outer artifact bytes")
    archive = _fixture_archive()
    first = inventory.render_inventory(executable, archive)

    archive.pyz.payloads["requests.sessions"] = b"changed bytecode"
    second = inventory.render_inventory(executable, archive)

    assert first != second


def test_base_library_fingerprint_ignores_zip_order_but_binds_member_bytes():
    def build(entries: list[tuple[str, bytes]]) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name, payload in entries:
                archive.writestr(name, payload)
        return output.getvalue()

    first = build([("a.pyc", b"a"), ("b.pyc", b"b")])
    reordered = build([("b.pyc", b"b"), ("a.pyc", b"a")])
    changed = build([("a.pyc", b"a"), ("b.pyc", b"changed")])

    first_identity = inventory._fingerprint_payload_identity("base_library.zip", first)
    assert first_identity == inventory._fingerprint_payload_identity(
        "base_library.zip", reordered
    )
    assert first_identity != inventory._fingerprint_payload_identity(
        "base_library.zip", changed
    )


def test_render_inventory_truthfully_counts_forbidden_payloads(tmp_path):
    executable = tmp_path / "old.exe"
    executable.write_bytes(b"old artifact")
    archive = _fixture_archive()
    additions = {
        "PyQt6\\QtCore.pyd": b"pyqt",
        "vendor\\bgutil-ytdlp-pot-provider\\build\\generate_once.js": b"js",
        "node_modules\\canvas\\build\\Release\\canvas.node": b"canvas",
    }
    for name, payload in additions.items():
        archive.payloads[name] = payload
        archive.toc[name] = (0, len(payload), len(payload), 0, "b")
    provider_module = "yt_dlp_plugins.extractor.getpot_bgutil"
    archive.pyz.payloads[provider_module] = b"provider bytecode"
    archive.pyz.toc[provider_module] = (0, 0, len(archive.pyz.payloads[provider_module]))

    report = inventory.render_inventory(executable, archive)

    assert "| PyQt code/binary/module | 1 | 0 | 1 |" in report
    assert "| bgutil/getpot/yt_dlp_plugins provider code/module | 1 | 1 | 2 |" in report
    assert "| Raw JavaScript/TypeScript payload | 1 | 0 | 1 |" in report
    assert "| canvas native/module payload | 1 | 0 | 1 |" in report


def test_generate_writes_only_the_explicit_output_atomically(tmp_path):
    executable = tmp_path / "artifact.exe"
    executable.write_bytes(b"artifact")
    output = tmp_path / "generated" / "inventory.txt"
    root_audit = tmp_path / "THIRD_PARTY_LICENSES.txt"
    root_audit.write_text("do not overwrite", encoding="utf-8")
    archive = _fixture_archive()

    rendered = inventory.generate(
        executable,
        output,
        archive_factory=lambda _: archive,
    )

    assert output.read_text(encoding="utf-8") == rendered
    assert root_audit.read_text(encoding="utf-8") == "do not overwrite"
    assert not list(output.parent.glob(".*.tmp"))


def test_inventory_rejects_ambiguous_pyz_and_case_collisions(tmp_path):
    executable = tmp_path / "artifact.exe"
    executable.write_bytes(b"artifact")

    with pytest.raises(inventory.InventoryError, match="exactly one embedded PYZ"):
        inventory.render_inventory(executable, FakeCArchive({}, pyz_count=2))

    archive = _fixture_archive()
    archive.payloads["LIBFFI-8.DLL"] = b"collision"
    archive.toc["LIBFFI-8.DLL"] = (0, 9, 9, 0, "b")
    with pytest.raises(inventory.InventoryError, match="case-insensitive CArchive collision"):
        inventory.render_inventory(executable, archive)


def test_documentation_mentions_do_not_break_zero_code_counts(tmp_path):
    executable = tmp_path / "artifact.exe"
    executable.write_bytes(b"artifact")
    archive = _fixture_archive()
    notice = "licenses\\historical-PyQt6-bgutil.txt"
    archive.payloads[notice] = b"historical audit evidence"
    archive.toc[notice] = (0, 25, 25, 0, "b")

    report = inventory.render_inventory(executable, archive)

    assert "| PyQt code/binary/module | 0 | 0 | 0 |" in report
    assert "| bgutil/getpot/yt_dlp_plugins provider code/module | 0 | 0 | 0 |" in report
