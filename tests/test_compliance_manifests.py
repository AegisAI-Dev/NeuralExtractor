from __future__ import annotations

import hashlib

from scripts.generate_compliance_manifests import verify_manifest


def test_manifest_verifier_accepts_safe_matching_entry(tmp_path):
    payload = tmp_path / "nested" / "payload.txt"
    payload.parent.mkdir()
    payload.write_text("notice\n", encoding="utf-8")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.sha256"
    manifest.write_text(f"{digest}  nested/payload.txt\n", encoding="utf-8")

    assert verify_manifest(manifest, tmp_path) == []


def test_manifest_verifier_rejects_mismatch_and_parent_escape(tmp_path):
    manifest = tmp_path / "manifest.sha256"
    manifest.write_text(f"{'0' * 64}  ../outside.txt\n", encoding="utf-8")

    errors = verify_manifest(manifest, tmp_path)

    assert errors == ["line 1: unsafe path '../outside.txt'"]


def test_manifest_verifier_rejects_incomplete_and_unexpected_coverage(tmp_path):
    listed = tmp_path / "listed.txt"
    listed.write_text("listed\n", encoding="utf-8")
    omitted = tmp_path / "omitted.txt"
    omitted.write_text("omitted\n", encoding="utf-8")
    digest = hashlib.sha256(listed.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.sha256"
    manifest.write_text(f"{digest}  listed.txt\n", encoding="utf-8")

    assert verify_manifest(
        manifest,
        tmp_path,
        expected_paths=[omitted],
    ) == [
        "manifest omits file: omitted.txt",
        "manifest contains unexpected file: listed.txt",
    ]
