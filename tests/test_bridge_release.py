"""Contract tests for the owner-authorized V3.0.8 family bridge release.

The bridge workflow exists so an installed V3.0.7 one-file build can detect,
verify and install 3.0.8. These tests pin the narrow guarantees that make that
safe: exact manual inputs, default-branch and new-tag requirements, exactly the
four updater assets V3.0.7 consumes, a stable (non-draft, non-prerelease)
release, prohibited-hash and payload-boundary rejection, and the updater
compatibility path from 3.0.7 to 3.0.8.

They also pin that the bridge does NOT weaken the compliance-gated production
workflow and does not flip any audit status to PASS.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from neural_extractor_v3.config import VERSION
from neural_extractor_v3.core.update_manifest import (
    UpdateManifest,
    UpdateValidationError,
    expected_checksum_filename,
    expected_exe_filename,
    expected_manifest_filename,
    is_newer_version,
)
from neural_extractor_v3.core.updater import UpdateChecker
from scripts import verify_packaged_licensing as packaged

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "build-bridge-release.yml"
PRODUCTION_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "build-release.yml"
BRIDGE_SPEC = PROJECT_ROOT / "NeuralExtractorV3-bridge-onefile.spec"
BRIDGE_VERSION = "3.0.8"
BRIDGE_CONFIRMATION = "PUBLISH-FAMILY-BRIDGE-3.0.8"
LEGACY_308_SHA256 = "0d4d4bdf1eabf5af88c1094732ae28cf55f12a0dc36377d90088eb54537b82ac"
LEGACY_304_SHA256 = "02fbde8845bcb7b8946a44f320aa1f88a63a70ceac9765f800276ce11bfa6ed7"


@pytest.fixture(scope="module")
def bridge_workflow() -> str:
    return BRIDGE_WORKFLOW.read_text(encoding="utf-8")


def test_bridge_workflow_runs_only_on_manual_dispatch(bridge_workflow: str):
    assert "workflow_dispatch:" in bridge_workflow
    trigger_block = bridge_workflow.split("permissions:", 1)[0]
    assert re.search(r"(?m)^on:\s*$", trigger_block)
    # No automatic push/tag/schedule/pull-request trigger may exist.
    for forbidden in ("push:", "schedule:", "pull_request:", "release:", "tags:"):
        assert forbidden not in trigger_block, f"bridge workflow must not trigger on {forbidden}"


def test_bridge_workflow_requires_both_exact_inputs(bridge_workflow: str):
    assert "version:" in bridge_workflow
    assert "confirmation:" in bridge_workflow
    assert bridge_workflow.count("required: true") >= 2
    assert f'BRIDGE_VERSION: "{BRIDGE_VERSION}"' in bridge_workflow
    assert f'BRIDGE_CONFIRMATION: "{BRIDGE_CONFIRMATION}"' in bridge_workflow


def test_bridge_workflow_rejects_any_other_version_or_confirmation(bridge_workflow: str):
    assert '$version -ne $env:BRIDGE_VERSION' in bridge_workflow
    assert '$confirmation -ne $env:BRIDGE_CONFIRMATION' in bridge_workflow
    # Both mismatch branches must fail the run.
    validation = bridge_workflow.split("Validate bridge inputs", 1)[1].split("- name:", 1)[0]
    assert validation.count("exit 1") >= 3


def test_bridge_workflow_requires_default_branch(bridge_workflow: str):
    assert "github.event.repository.default_branch" in bridge_workflow
    assert "must run from the repository default branch" in bridge_workflow


def test_bridge_workflow_rejects_an_existing_tag(bridge_workflow: str):
    assert "git.getRef" in bridge_workflow
    assert "tags/${tag}" in bridge_workflow
    assert "already exists" in bridge_workflow
    assert "core.setFailed" in bridge_workflow
    assert "error.status !== 404" in bridge_workflow


def test_bridge_workflow_publishes_exactly_the_four_updater_assets(bridge_workflow: str):
    required = (
        "NeuralExtractorV3.exe",
        f"NeuralExtractorV3-{BRIDGE_VERSION}-windows-x64.exe",
        f"NeuralExtractorV3-{BRIDGE_VERSION}-windows-x64.exe.sha256",
        f"NeuralExtractorV3-{BRIDGE_VERSION}-manifest.json",
    )
    publish_block = bridge_workflow.split("Publish the stable bridge release", 1)[1]
    for asset in required:
        assert f"dist/{asset}" in publish_block, f"missing published asset {asset}"
    # The one-folder ZIP must not be the bridge payload: V3.0.7 cannot consume it.
    assert "windows-x64.zip" not in publish_block
    assert "corresponding-source" not in publish_block
    # The exact-asset gate must compare against exactly these four names.
    assert 'Compare-Object $expected $actual' in bridge_workflow
    assert "must contain exactly the four updater assets" in bridge_workflow


def test_bridge_asset_names_match_what_the_v307_updater_requests():
    assert expected_exe_filename(BRIDGE_VERSION) == (
        f"NeuralExtractorV3-{BRIDGE_VERSION}-windows-x64.exe"
    )
    assert expected_manifest_filename(BRIDGE_VERSION) == (
        f"NeuralExtractorV3-{BRIDGE_VERSION}-manifest.json"
    )
    assert expected_checksum_filename(BRIDGE_VERSION) == (
        f"NeuralExtractorV3-{BRIDGE_VERSION}-windows-x64.exe.sha256"
    )


def test_bridge_release_is_stable_not_draft_or_prerelease(bridge_workflow: str):
    publish_block = bridge_workflow.split("Publish the stable bridge release", 1)[1]
    assert "draft: false" in publish_block
    assert "prerelease: false" in publish_block
    assert 'make_latest: "true"' in publish_block
    assert "tag_name: v3.0.8" in publish_block


def test_bridge_workflow_validates_before_building_and_publishing(bridge_workflow: str):
    order = [
        "Validate bridge inputs",
        "Require a new bridge tag",
        "Confirm project version is 3.0.8",
        "Install locked dependencies",
        "Stage pinned Node, FFmpeg and ffprobe",
        "Validate source, tests and manifests",
        "Build the one-file bridge EXE",
        "Confirm packaged version is 3.0.8",
        "Run packaged runtime, GUI, Unicode and provider smokes",
        "Run simulated 3.0.7 to 3.0.8 updater handoff and rollback smoke",
        "Scan the packaged EXE for PyQt6 and provider payloads",
        "Scan outputs for prohibited legacy hashes",
        "Generate the versioned EXE, checksum and updater manifest",
        "Verify the manifest against the final EXE",
        "Publish the stable bridge release",
    ]
    positions = [bridge_workflow.index(step) for step in order]
    assert positions == sorted(positions), "bridge workflow steps are out of order"
    for command in (
        "-m ruff check src tests scripts main.py",
        "-m compileall -q src scripts main.py",
        "-m pytest tests -q",
        "scripts/generate_project_metadata.py --check",
        "scripts/generate_compliance_manifests.py --check",
        "scripts/verify_distribution_boundary.py .",
        "scripts/release_tools.py validate --release-ref $env:BRIDGE_TAG",
    ):
        assert command in bridge_workflow, f"bridge workflow is missing: {command}"


def test_bridge_workflow_waits_for_the_windowed_exe_when_checking_version(
    bridge_workflow: str,
):
    """PowerShell does not wait for a GUI-subsystem process invoked directly."""
    version_block = bridge_workflow.split("Confirm packaged version is 3.0.8", 1)[1].split(
        "- name:", 1
    )[0]
    assert "Start-Process" in version_block
    assert "-Wait" in version_block
    assert "-RedirectStandardOutput" in version_block
    assert "$process.ExitCode -ne 0" in version_block
    assert 'NeuralExtractorV3 $($env:BRIDGE_VERSION)' in version_block
    # A bare call would silently capture nothing.
    code_lines = [
        line for line in version_block.splitlines() if not line.strip().startswith("#")
    ]
    assert not any('& "dist\\NeuralExtractorV3.exe" --version' in line for line in code_lines)


def test_bridge_workflow_rejects_both_prohibited_hashes(bridge_workflow: str):
    assert LEGACY_308_SHA256 in bridge_workflow
    assert LEGACY_304_SHA256 in bridge_workflow
    assert "Prohibited legacy artifact detected" in bridge_workflow
    scan_block = bridge_workflow.split("Scan outputs for prohibited legacy hashes", 1)[1]
    assert '@("dist", "build")' in scan_block
    assert "-Recurse -File -Force" in scan_block
    assert "exit 1" in scan_block


def test_bridge_workflow_builds_clean_from_source_without_local_artifacts(bridge_workflow: str):
    build_block = bridge_workflow.split("Build the one-file bridge EXE", 1)[1].split(
        "- name:", 1
    )[0]
    assert "Remove-Item dist -Recurse -Force" in build_block
    assert "NeuralExtractorV3-bridge-onefile.spec" in build_block
    assert "--clean --noconfirm" in build_block
    assert "Quarantined Legacy Builds" not in bridge_workflow


def test_bridge_workflow_generates_manifest_with_bootstrap_updater_floor(bridge_workflow: str):
    assert 'BRIDGE_MINIMUM_UPDATER_VERSION: "3.0.4"' in bridge_workflow
    assert (
        "scripts/release_tools.py manifest --version $version --exe $versioned "
        "--output $manifest --minimum-updater-version $env:BRIDGE_MINIMUM_UPDATER_VERSION"
    ) in bridge_workflow
    verify_block = bridge_workflow.split("Verify the manifest against the final EXE", 1)[1]
    for assertion in (
        "asset_sha256 -ne $actualHash",
        "asset_size -ne $actualSize",
        "asset_filename -ne",
        "channel -ne \"stable\"",
        "minimum_updater_version -ne",
    ):
        assert assertion in verify_block, f"manifest verification is missing: {assertion}"


def test_bridge_workflow_logs_the_hold_warning(bridge_workflow: str):
    warning = (
        "Owner-authorized V3.0.8 family bridge release. "
        "General compliance status remains HOLD."
    )
    assert bridge_workflow.count(warning) >= 2
    assert f"::warning::{warning}" in bridge_workflow


def test_bridge_workflow_never_edits_compliance_documents(bridge_workflow: str):
    # The bridge path may skip the public compliance gate, but it must never
    # rewrite audit status documents or fabricate a qualified-review PASS.
    for forbidden in (
        "Qualified-review-status: PASS",
        "Release-gate-status: PASS",
        "Audit-blocker-count: 0",
        "public_distribution_verdict",
    ):
        assert forbidden not in bridge_workflow, f"bridge workflow must not write {forbidden}"
    for document in (
        "THIRD_PARTY_NOTICES.md",
        "THIRD_PARTY_LICENSES.txt",
        "docs/DEPENDENCY-SOURCE.md",
        "docs\\DEPENDENCY-SOURCE.md",
        "docs/LGPL-COMPLIANCE.md",
    ):
        assert f"Set-Content {document}" not in bridge_workflow
        assert f"Out-File {document}" not in bridge_workflow


def test_production_workflow_remains_fail_closed_and_unmodified_by_the_bridge():
    production = PRODUCTION_WORKFLOW.read_text(encoding="utf-8")
    assert "Enforce licensing release gate" in production
    assert "Licensing audit status is HOLD. Public build/release is blocked." in production
    for gate in (
        "Release-gate-status: PASS",
        "Audit-blocker-count: 0",
        "Qualified-review-status: PASS",
    ):
        assert gate in production, f"production gate lost its {gate} requirement"
    # The production workflow must keep building the audited one-folder spec and
    # must not adopt the bridge one-file spec.
    assert "NeuralExtractorV3.spec" in production
    assert "NeuralExtractorV3-bridge-onefile.spec" not in production
    assert "PUBLISH-FAMILY-BRIDGE" not in production


def test_bridge_spec_builds_one_file_without_pyqt_or_provider_payloads():
    spec = BRIDGE_SPEC.read_text(encoding="utf-8")
    # One-file form: the EXE collects binaries/datas and there is no COLLECT.
    assert "exclude_binaries=True" not in spec
    assert "COLLECT(" not in spec
    assert "a.binaries," in spec and "a.datas," in spec
    for excluded in ("PyQt5", "PyQt6", "yt_dlp_plugins", "bgutil_ytdlp_pot_provider"):
        assert excluded in spec, f"bridge spec must exclude {excluded}"
    # Pinned audited native inputs are preserved.
    for pinned in (
        "39d45b5933f339d3ebdebd76474893dab5d7da1038920f65cf5bbcf0f20f3636",
        "6ed7e5c931d3cbc72931ee7e97efc4b7d8a1287f03c60585fab81a6a293b2e0e",
        "55a3d20229c2373dade4362215c9bd5a04b59d4e734d0bbb882afd9cea4fb046",
        "d1682615247e165ba8aa0cff59e090a0b1b6b90793e48733f441dff8d8e6328e",
        "6968228b18fc86b0b02f3dbf2c879c2c6f689a66130a72f35a3f0b2755d99e41",
    ):
        assert pinned in spec
    assert "noarchive=False" in spec
    assert "upx=False" in spec
    assert 'raise SystemExit(\n        "GPL provider sources are present' in spec
    # The audited one-folder spec must remain the compliance candidate.
    assert "NeuralExtractorV3.spec" in spec


def _bridge_archive(monkeypatch):
    """A valid one-file archive plus the bundled runtimes a bridge EXE must ship."""
    from tests.test_distribution_verifiers import _valid_archive

    archive = _valid_archive(monkeypatch)
    for runtime in packaged.BRIDGE_REQUIRED_RUNTIME_PATHS:
        key = runtime.replace("/", "\\")
        payload = f"runtime:{runtime}".encode()
        archive.payloads[key] = payload
        archive.toc[key] = (0, len(payload), len(payload), 0, "b")
    return archive


def test_bridge_boundary_accepts_a_provider_free_bridge_archive(monkeypatch):
    assert packaged.verify_bridge_boundary(_bridge_archive(monkeypatch)) == []


def test_bridge_boundary_scan_rejects_pyqt_and_provider_payloads(monkeypatch):
    from tests.test_distribution_verifiers import FakePyz

    for path, expected in (
        ("PyQt6\\QtCore.pyd", "PyQt code or binary"),
        ("vendor\\bgutil-ytdlp-pot-provider\\LICENSE", "in-process provider code"),
        ("payload\\generate_once.js", "raw JavaScript/TypeScript"),
        ("payload\\generate_once.ts.map", "raw JavaScript/TypeScript"),
        ("node_modules\\canvas\\build\\Release\\canvas.node", "canvas native"),
    ):
        tainted = _bridge_archive(monkeypatch)
        tainted.payloads[path] = b"payload"
        tainted.toc[path] = (0, 7, 7, 0, "b")
        errors = packaged.verify_bridge_boundary(tainted)
        assert any(expected in error for error in errors), f"{path} was not rejected"

    for modules, expected in (
        (("PySide6", "PyQt6"), "PyQt module is forbidden"),
        (("PySide6", "getpot_bgutil"), "provider module is forbidden"),
        (("PySide6", "yt_dlp_plugins.extractor.getpot_bgutil"), "provider module is forbidden"),
    ):
        tainted_pyz = _bridge_archive(monkeypatch)
        tainted_pyz.pyz = FakePyz(modules)
        errors = packaged.verify_bridge_boundary(tainted_pyz)
        assert any(expected in error for error in errors), f"{modules} was not rejected"


def test_bridge_boundary_requires_bundled_runtimes(monkeypatch):
    for runtime in packaged.BRIDGE_REQUIRED_RUNTIME_PATHS:
        stripped = _bridge_archive(monkeypatch)
        key = runtime.replace("/", "\\")
        del stripped.payloads[key]
        del stripped.toc[key]
        errors = packaged.verify_bridge_boundary(stripped)
        assert any(
            "missing bundled runtime payloads" in error and runtime in error
            for error in errors
        ), f"{runtime} removal was not rejected"


def test_bridge_boundary_requires_notices_and_audited_qt_payload(monkeypatch):
    stripped_notice = _bridge_archive(monkeypatch)
    del stripped_notice.payloads["THIRD_PARTY_NOTICES.md"]
    del stripped_notice.toc["THIRD_PARTY_NOTICES.md"]
    assert any(
        "missing required compliance paths" in error and "THIRD_PARTY_NOTICES.md" in error
        for error in packaged.verify_bridge_boundary(stripped_notice)
    )

    unaudited_qt = _bridge_archive(monkeypatch)
    unaudited_qt.payloads["PySide6\\Qt6Pdf.dll"] = b"unaudited"
    unaudited_qt.toc["PySide6\\Qt6Pdf.dll"] = (0, 9, 9, 0, "b")
    assert any(
        "unaudited PySide6/Qt paths" in error
        for error in packaged.verify_bridge_boundary(unaudited_qt)
    )


def test_bridge_boundary_cli_rejects_prohibited_legacy_hash(tmp_path, monkeypatch):
    artifact = tmp_path / "legacy.exe"
    artifact.write_bytes(b"legacy payload")
    monkeypatch.setattr(
        packaged,
        "PROHIBITED_LEGACY_SHA256S",
        frozenset({hashlib.sha256(b"legacy payload").hexdigest()}),
    )

    assert packaged.verify_bridge(artifact) == [
        "artifact is a prohibited legacy one-file EXE"
    ]


def test_v307_detects_v308_as_newer():
    assert is_newer_version("3.0.8", "3.0.7")
    assert not is_newer_version("3.0.7", "3.0.8")
    assert not is_newer_version("3.0.8", "3.0.8")


def _bridge_release_payload(*, exe_size: int, draft: bool = False, prerelease: bool = False):
    base = "https://github.com/AegisAI-Dev/NeuralExtractor/releases/download/v3.0.8"
    return {
        "tag_name": "v3.0.8",
        "name": "Neural Extractor V3 v3.0.8",
        "draft": draft,
        "prerelease": prerelease,
        "html_url": "https://github.com/AegisAI-Dev/NeuralExtractor/releases/tag/v3.0.8",
        "published_at": "2026-07-26T00:00:00Z",
        "body": "bridge release",
        "assets": [
            {
                "name": expected_exe_filename(BRIDGE_VERSION),
                "browser_download_url": f"{base}/{expected_exe_filename(BRIDGE_VERSION)}",
                "size": exe_size,
            },
            {
                "name": expected_manifest_filename(BRIDGE_VERSION),
                "browser_download_url": f"{base}/{expected_manifest_filename(BRIDGE_VERSION)}",
                "size": 512,
            },
            {
                "name": expected_checksum_filename(BRIDGE_VERSION),
                "browser_download_url": f"{base}/{expected_checksum_filename(BRIDGE_VERSION)}",
                "size": 107,
            },
        ],
    }


def test_v307_updater_accepts_the_bridge_release_manifest():
    """A V3.0.7 client must parse the bridge release and bind its manifest."""
    exe_bytes = b"bridge payload" * 100_000
    exe_size = len(exe_bytes)
    manifest = UpdateManifest(
        schema_version=1,
        application_name="Neural Extractor V3",
        release_version=BRIDGE_VERSION,
        asset_filename=expected_exe_filename(BRIDGE_VERSION),
        asset_sha256=hashlib.sha256(exe_bytes).hexdigest(),
        asset_size=exe_size,
        platform="windows",
        architecture="x64",
        channel="stable",
        minimum_updater_version="3.0.4",
    )
    checker = UpdateChecker()
    candidate = checker.parse_release(
        _bridge_release_payload(exe_size=exe_size), current_version="3.0.7"
    )
    assert candidate is not None
    assert candidate.version == BRIDGE_VERSION

    info = checker.bind_manifest(candidate, manifest.to_json(), "3.0.7")
    assert info.version == BRIDGE_VERSION
    assert info.manifest.asset_filename == expected_exe_filename(BRIDGE_VERSION)
    assert info.manifest.asset_size == exe_size
    assert info.manifest.minimum_updater_version == "3.0.4"
    assert info.download_size == exe_size


def test_v307_updater_would_ignore_a_draft_or_prerelease_bridge_release():
    """This is why the bridge workflow must publish a stable release."""
    checker = UpdateChecker()
    assert (
        checker.parse_release(
            _bridge_release_payload(exe_size=2_000_000, draft=True), current_version="3.0.7"
        )
        is None
    )
    assert (
        checker.parse_release(
            _bridge_release_payload(exe_size=2_000_000, prerelease=True),
            current_version="3.0.7",
        )
        is None
    )


def test_bridge_manifest_rejects_a_mismatched_minimum_updater_version():
    """A 3.0.7 client must be allowed; a floor above 3.0.7 must reject it."""
    exe_bytes = b"bridge payload" * 100_000
    document = json.dumps(
        {
            "schema_version": 1,
            "application_name": "Neural Extractor V3",
            "release_version": BRIDGE_VERSION,
            "asset_filename": expected_exe_filename(BRIDGE_VERSION),
            "asset_sha256": hashlib.sha256(exe_bytes).hexdigest(),
            "asset_size": len(exe_bytes),
            "platform": "windows",
            "architecture": "x64",
            "channel": "stable",
            "minimum_updater_version": "3.0.9",
        }
    )
    with pytest.raises(UpdateValidationError) as excinfo:
        UpdateManifest.from_json(
            document, release_version=BRIDGE_VERSION, current_version="3.0.7"
        )
    assert excinfo.value.code == "updater_too_old"

    accepted = UpdateManifest.from_json(
        document.replace('"3.0.9"', '"3.0.4"'),
        release_version=BRIDGE_VERSION,
        current_version="3.0.7",
    )
    assert accepted.minimum_updater_version == "3.0.4"


def test_bridge_workflow_drives_the_real_updater_replacement_and_rollback_smokes(
    bridge_workflow: str,
):
    smoke_block = bridge_workflow.split(
        "Run simulated 3.0.7 to 3.0.8 updater handoff and rollback smoke", 1
    )[1].split("- name:", 1)[0]
    assert "scripts/packaged_updater_smoke.py" in smoke_block
    assert "--scenario all" in smoke_block
    assert "simulated-3.0.7" in smoke_block
    assert "must differ from the 3.0.8 payload" in smoke_block
    # The updater fail-closes when the target executable resolves inside
    # tempfile.gettempdir(), and TEMP is RUNNER_TEMP on Windows runners, so the
    # simulated install must be staged outside RUNNER_TEMP or the smoke can
    # never pass.
    code_lines = [
        line for line in smoke_block.splitlines() if not line.strip().startswith("#")
    ]
    assert not any("RUNNER_TEMP" in line for line in code_lines)
    assert 'Join-Path $PWD "build\\upd-smoke"' in smoke_block
    # The smoke nests ~190 characters below its workspace; a long workspace path
    # makes the detached-helper launch fail with WinError 206.
    workspace_line = next(line for line in code_lines if "$workspace =" in line)
    assert len(workspace_line.split('"')[1]) <= 20


def test_updater_rejects_an_install_target_inside_the_temporary_root(tmp_path):
    """Locks in why the bridge smoke workspace lives outside RUNNER_TEMP."""
    from neural_extractor_v3.core.update_installer import assess_installation_capability

    exe_bytes = b"bridge payload" * 100_000
    manifest = UpdateManifest(
        schema_version=1,
        application_name="Neural Extractor V3",
        release_version=BRIDGE_VERSION,
        asset_filename=expected_exe_filename(BRIDGE_VERSION),
        asset_sha256=hashlib.sha256(exe_bytes).hexdigest(),
        asset_size=len(exe_bytes),
        platform="windows",
        architecture="x64",
        channel="stable",
        minimum_updater_version="3.0.4",
    )
    temporary_root = tmp_path / "temp-root"
    install = temporary_root / "install"
    install.mkdir(parents=True)
    target = install / "NeuralExtractorV3.exe"
    target.write_bytes(b"packaged")

    rejected = assess_installation_capability(
        manifest,
        target_executable=target,
        frozen=True,
        updates_root=tmp_path / "updates",
        temporary_root=temporary_root,
    )
    assert not rejected.available
    assert rejected.code == "invalid_install_location"

    outside = tmp_path / "program" / "NeuralExtractorV3.exe"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"packaged")
    accepted = assess_installation_capability(
        manifest,
        target_executable=outside,
        frozen=True,
        updates_root=tmp_path / "updates",
        temporary_root=temporary_root,
    )
    assert accepted.code != "invalid_install_location"


def test_packaged_updater_smoke_covers_confirmation_and_rollback_paths():
    """The smoke the bridge workflow runs must assert startup confirmation and rollback."""
    smoke = (PROJECT_ROOT / "scripts" / "packaged_updater_smoke.py").read_text(
        encoding="utf-8"
    )
    assert "_success_smoke" in smoke
    assert "_timeout_rollback_smoke" in smoke
    assert "TransactionState.CONFIRMED" in smoke
    assert "TransactionState.ROLLED_BACK" in smoke
    assert "rollback_succeeded" in smoke
    assert "startup_confirmation_timeout" in smoke
    assert "Confirmed update did not replace target" in smoke
    assert "Rollback did not restore original target" in smoke


def test_bridge_version_matches_the_application_source():
    assert VERSION == BRIDGE_VERSION
