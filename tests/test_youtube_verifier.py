from types import SimpleNamespace

from neural_extractor_v3.core import youtube_verifier as verifier_module
from neural_extractor_v3.core.downloader import (
    YtdlpCapturedOutput,
    YtdlpRunError,
    YtdlpRunResult,
)
from neural_extractor_v3.core.youtube_verifier import verify_dedicated_youtube_profile


def test_mocked_verification_is_metadata_only_bounded_and_classifies_po_warning(
    tmp_path, monkeypatch
):
    captured = {}

    class FakeEngine:
        def __init__(self, options, *, process_record_label, process_limits):
            captured["options"] = options
            captured["label"] = process_record_label
            captured["limits"] = process_limits
            self.js_runtime_status = SimpleNamespace(found=True)

        def run_authentication_preflight(self, url, profile):
            captured["url"] = url
            captured["profile"] = profile
            return YtdlpRunResult(
                metadata={"id": "abc123", "title": "Offline test"},
                diagnostic="WARNING: This client may require a PO Token",
            )

    monkeypatch.setattr(verifier_module, "DownloadEngine", FakeEngine)
    result = verify_dedicated_youtube_profile(
        tmp_path / "profile",
        "https://www.youtube.com/watch?v=abc123",
    )

    assert result.success
    assert result.code == "connected"
    assert "PO Token" in result.warning
    assert captured["label"] == "youtube-verification"
    assert captured["limits"].total_timeout == 90
    assert captured["options"].subtitles is False
    assert captured["options"].thumbnail is False


def test_mocked_verification_classifies_rotated_session_separately(tmp_path, monkeypatch):
    class FakeEngine:
        def __init__(self, *_args, **_kwargs):
            self.js_runtime_status = SimpleNamespace(found=True)

        def run_authentication_preflight(self, url, profile):
            del url, profile
            raise YtdlpRunError(
                "yt-dlp <redacted>",
                YtdlpCapturedOutput(
                    stderr=["WARNING: cookies are no longer valid. Login required."]
                ),
                exit_code=1,
            )

    monkeypatch.setattr(verifier_module, "DownloadEngine", FakeEngine)
    result = verify_dedicated_youtube_profile(
        tmp_path / "profile",
        "https://www.youtube.com/watch?v=abc123",
    )
    assert not result.success
    assert result.code == "expired"
    assert "cookie" not in result.message.casefold()

