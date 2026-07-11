import json
from pathlib import Path

import pytest
from neural_extractor_v3.core.update_manifest import MIN_UPDATE_SIZE_BYTES

from scripts.release_tools import generate_manifest, validate_release_versions


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


def test_release_version_validation_rejects_source_disagreement_and_invalid_semver(tmp_path):
    write_project_versions(tmp_path, "3.0.2", "3.0.3")
    with pytest.raises(ValueError, match="Version mismatch"):
        validate_release_versions(tmp_path, "v3.0.2")

    write_project_versions(tmp_path, "3.0.2-beta", "3.0.2-beta")
    with pytest.raises(ValueError):
        validate_release_versions(tmp_path, "v3.0.2-beta")


def test_manifest_generator_hashes_exact_versioned_executable(tmp_path):
    executable = tmp_path / "NeuralExtractorV3-3.0.2-windows-x64.exe"
    executable.write_bytes(b"E" * MIN_UPDATE_SIZE_BYTES)
    output = tmp_path / "NeuralExtractorV3-3.0.2-manifest.json"

    manifest = generate_manifest(
        version="3.0.2",
        executable=executable,
        output=output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert manifest.asset_size == MIN_UPDATE_SIZE_BYTES
    assert payload["asset_filename"] == executable.name
    assert payload["release_version"] == "3.0.2"
    assert payload["minimum_updater_version"] == "3.0.2"


def test_workflow_contains_mandatory_version_gate_and_manifest_publication():
    workflow = Path(".github/workflows/build-release.yml").read_text(encoding="utf-8")

    assert 'tags:\n      - "v*.*.*"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "scripts/release_tools.py validate" in workflow
    assert "scripts/release_tools.py manifest" in workflow
    assert "NeuralExtractorV3*-manifest.json" in workflow
    assert "Manual releases must run from the repository default branch." in workflow
    assert "Require a new tag for manual releases" in workflow
    assert "Tag ${tag} already exists" in workflow
    assert "target_commitish: ${{ github.sha }}" in workflow
    assert "release_tag" not in workflow
