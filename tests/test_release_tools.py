import json
from pathlib import Path

import pytest

from neural_extractor_v3.core.update_manifest import MIN_UPDATE_SIZE_BYTES, is_newer_version
from scripts.release_tools import generate_manifest, validate_release_versions

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_project_versions(root: Path, config_version: str, package_version: str) -> None:
    config = root / "src" / "neural_extractor_v3" / "config.py"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f'APP_NAME = "Neural Extractor V3"\nVERSION = "{config_version}"\n')
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "neural-extractor-v3"\nversion = "{package_version}"\n'
    )


def test_release_version_validation_requires_tag_and_both_sources_to_match(tmp_path):
    write_project_versions(tmp_path, "3.0.2", "3.0.2")

    assert validate_release_versions(tmp_path, "v3.0.2") == "3.0.2"
    assert validate_release_versions(tmp_path, "3.0.2") == "3.0.2"

    with pytest.raises(ValueError, match="Release version mismatch"):
        validate_release_versions(tmp_path, "v3.0.3")


def test_current_306_source_versions_and_release_ref_are_consistent():
    assert validate_release_versions(PROJECT_ROOT, "v3.0.6") == "3.0.6"


def test_304_is_newer_than_both_affected_updater_versions():
    assert is_newer_version("3.0.4", "3.0.2")
    assert is_newer_version("3.0.4", "3.0.3")
    assert not is_newer_version("3.0.4", "3.0.4")


def test_release_version_validation_rejects_source_disagreement_and_invalid_semver(tmp_path):
    write_project_versions(tmp_path, "3.0.2", "3.0.3")
    with pytest.raises(ValueError, match="Version mismatch"):
        validate_release_versions(tmp_path, "v3.0.2")

    write_project_versions(tmp_path, "3.0.2-beta", "3.0.2-beta")
    with pytest.raises(ValueError):
        validate_release_versions(tmp_path, "v3.0.2-beta")


def test_manifest_generator_hashes_exact_versioned_executable(tmp_path):
    executable = tmp_path / "NeuralExtractorV3-3.0.4-windows-x64.exe"
    executable.write_bytes(b"E" * MIN_UPDATE_SIZE_BYTES)
    output = tmp_path / "NeuralExtractorV3-3.0.4-manifest.json"

    manifest = generate_manifest(
        version="3.0.4",
        executable=executable,
        output=output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert manifest.asset_size == MIN_UPDATE_SIZE_BYTES
    assert payload["asset_filename"] == executable.name
    assert payload["release_version"] == "3.0.4"
    assert payload["minimum_updater_version"] == "3.0.4"


def test_workflow_contains_mandatory_version_gate_and_manifest_publication():
    workflow = Path(".github/workflows/build-release.yml").read_text(encoding="utf-8")

    assert 'tags:\n      - "v*.*.*"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "scripts/release_tools.py validate" in workflow
    assert "scripts/release_tools.py manifest" in workflow
    assert "--minimum-updater-version 3.0.4" in workflow
    assert "Stage verified bundled runtimes" in workflow
    assert "Pinned FFmpeg archive checksum mismatch" in workflow
    assert 'node-version: "22.17.0"' in workflow
    assert 'foreach ($runtime in @("bin\\\\node.exe", "bin\\\\ffmpeg.exe", "bin\\\\ffprobe.exe"))' in workflow
    assert "Release output does not contain the exact required four files." in workflow
    assert "body_path: docs/release-notes/V${{ steps.release.outputs.version }}.md" in workflow
    assert "fail_on_unmatched_files: true" in workflow
    assert "NeuralExtractorV3*.exe" not in workflow
    assert "NeuralExtractorV3*.sha256" not in workflow
    assert "NeuralExtractorV3*-manifest.json" not in workflow
    assert "Manual releases must run from the repository default branch." in workflow
    assert "Require a new tag for manual releases" in workflow
    assert "Tag ${tag} already exists" in workflow
    assert "target_commitish: ${{ github.sha }}" in workflow
    assert "release_tag" not in workflow


def test_release_notes_and_packaging_require_all_v304_runtime_and_handoff_guarantees():
    notes = Path("docs/release-notes/V3.0.4.md").read_text(encoding="utf-8")
    spec = Path("NeuralExtractorV3.spec").read_text(encoding="utf-8")

    for statement in (
        "Another updater process owns this installation",
        "GUI-to-helper transaction ownership handoff",
        "PID plus process-creation identity",
        "stale updater-state recovery",
        "genuinely concurrent updater processes",
        "SHA-256 and file-size verification",
        "startup confirmation",
        "V3.0.3 YouTube reliability fixes",
        "V3.0.2 and V3.0.3 users may need to install V3.0.4 manually once",
        "Future compatible updates from V3.0.4",
        "unsigned",
        "AegisAI-Dev/NeuralExtractor",
    ):
        assert statement in notes

    assert "A bundled node.exe is required" in spec
    assert "Bundled ffmpeg.exe and ffprobe.exe are required" in spec
    assert '(str(ffmpeg_bin / "ffmpeg.exe"), "bin")' in spec
    assert '(str(ffmpeg_bin / "ffprobe.exe"), "bin")' in spec
    assert 'binaries = [(str(node_runtime), "bin")]' in spec
