import tomllib
from pathlib import Path

from neural_extractor_v3.config import BUILD_LABEL, VERSION
from neural_extractor_v3.core.update_manifest import is_newer_version

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_v307_authoritative_versions_and_diagnostic_label_are_consistent():
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert VERSION == "3.0.7"
    assert project["project"]["version"] == "3.0.7"
    assert BUILD_LABEL == "unicode-safe-ytdlp-worker-hotfix"


def test_v306_updater_version_comparison_detects_v307_as_newer():
    assert is_newer_version("3.0.7", "3.0.6")
