import io
import json
import os
import subprocess
import sys
from pathlib import Path

from neural_extractor_v3.core import ytdlp_worker

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _parse_protocol_frames(output: bytes) -> list[dict]:
    lines = output.decode("utf-8").splitlines()
    assert lines
    assert all(line.startswith(ytdlp_worker.PROTOCOL_PREFIX) for line in lines)
    return [
        json.loads(line.removeprefix(ytdlp_worker.PROTOCOL_PREFIX))
        for line in lines
    ]


def test_worker_download_protocol_reports_phase_metadata_progress_and_success(monkeypatch):
    events = []
    captured_options = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            captured_options.update(options)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download=False):
            assert download is False
            return {
                "formats": [
                    {
                        "format_id": "18",
                        "ext": "mp4",
                        "vcodec": "avc1",
                        "acodec": "mp4a",
                        "height": 360,
                    }
                ]
            }

        def download(self, urls):
            captured_options["progress_hooks"][0](
                {
                    "status": "downloading",
                    "downloaded_bytes": 50,
                    "total_bytes": 100,
                    "info_dict": {"title": "Offline fake"},
                }
            )
            return 0

    monkeypatch.setattr(ytdlp_worker, "_emit", lambda kind, **payload: events.append((kind, payload)))
    monkeypatch.setattr(ytdlp_worker.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    exit_code = ytdlp_worker.run_worker(
        {
            "url": "https://www.youtube.com/watch?v=offline",
            "options": {"format": "18", "cookiesfrombrowser": ["firefox"]},
            "playlist": False,
            "mode": "download",
            "activity_label": "Downloading video",
        }
    )

    assert exit_code == 0
    assert captured_options["cookiesfrombrowser"] == ("firefox",)
    assert [kind for kind, _payload in events] == [
        "phase",
        "metadata",
        "phase",
        "progress",
        "result",
    ]
    assert events[1][1]["formats"][0]["format_id"] == "18"


def test_worker_discovery_removes_requested_selector_and_never_downloads(monkeypatch):
    events = []
    captured_options = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            captured_options.update(options)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download=False):
            return {
                "formats": [
                    {
                        "format_id": "140",
                        "ext": "m4a",
                        "vcodec": "none",
                        "acodec": "mp4a",
                    }
                ]
            }

        def download(self, urls):
            raise AssertionError("format discovery must never download media")

    monkeypatch.setattr(ytdlp_worker, "_emit", lambda kind, **payload: events.append((kind, payload)))
    monkeypatch.setattr(ytdlp_worker.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    exit_code = ytdlp_worker.run_worker(
        {
            "url": "https://www.youtube.com/watch?v=offline",
            "options": {"format": "unavailable-progressive-selector"},
            "playlist": False,
            "mode": "discover",
        }
    )

    assert exit_code == 0
    assert "format" not in captured_options
    assert captured_options["skip_download"] is True
    assert captured_options["ignore_no_formats_error"] is True
    assert any(kind == "metadata" for kind, _payload in events)


def test_worker_failure_reports_phase_and_traceback_without_crashing_protocol(monkeypatch):
    events = []

    class FailingYoutubeDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download=False):
            raise RuntimeError("controlled offline failure")

    monkeypatch.setattr(ytdlp_worker, "_emit", lambda kind, **payload: events.append((kind, payload)))
    monkeypatch.setattr(ytdlp_worker.yt_dlp, "YoutubeDL", FailingYoutubeDL)

    exit_code = ytdlp_worker.run_worker(
        {
            "url": "https://www.youtube.com/watch?v=offline",
            "options": {},
            "playlist": False,
            "mode": "download",
        }
    )

    assert exit_code == 1
    error = next(payload for kind, payload in events if kind == "error")
    assert error["phase"] == "preflight"
    assert error["message"] == "controlled offline failure"
    assert "RuntimeError" in error["traceback"]


def test_protocol_stdout_is_unicode_json_without_unframed_logging(monkeypatch):
    stream = io.BytesIO()
    monkeypatch.setattr(ytdlp_worker, "_PROTOCOL_STREAM", stream)

    ytdlp_worker._emit(
        "metadata",
        title="Beyoncé 🛡️ 日本語 العربية",
        filepath=r"C:\Téléchargements\日本語\🚀.mp4",
    )

    raw_frame = stream.getvalue()
    line = raw_frame.decode("utf-8")
    assert line.count("\n") == 1
    assert line.startswith(ytdlp_worker.PROTOCOL_PREFIX)
    assert "日本語" in line
    event = json.loads(line.removeprefix(ytdlp_worker.PROTOCOL_PREFIX))
    assert event == {
        "kind": "metadata",
        "title": "Beyoncé 🛡️ 日本語 العربية",
        "filepath": r"C:\Téléchargements\日本語\🚀.mp4",
    }


def test_malformed_worker_json_emits_one_deterministic_error_event(monkeypatch):
    protocol_stream = io.BytesIO()
    monkeypatch.setattr(ytdlp_worker, "_PROTOCOL_STREAM", protocol_stream)
    monkeypatch.setattr(
        ytdlp_worker,
        "_stdio_stream",
        lambda fd, fallback, mode: io.StringIO("{not-json") if fd == 0 else fallback,
    )

    assert ytdlp_worker.main() == 2

    events = _parse_protocol_frames(protocol_stream.getvalue())
    assert len(events) == 1
    event = events[0]
    assert event["kind"] == "error"
    assert event["phase"] == "startup"
    assert event["message"].startswith("Invalid internal request:")


def test_partial_binary_writes_keep_sequential_unicode_frames_complete(monkeypatch):
    class PartialWriter(io.BytesIO):
        def write(self, value):
            return super().write(bytes(value[:7]))

    stream = PartialWriter()
    monkeypatch.setattr(ytdlp_worker, "_PROTOCOL_STREAM", stream)

    ytdlp_worker.ProtocolLogger().debug(ytdlp_worker.PROTOCOL_SMOKE_TITLE)
    ytdlp_worker.ProtocolLogger().warning("字幕 ❤️ Русская музыка العربية")

    events = _parse_protocol_frames(stream.getvalue())
    assert [event["kind"] for event in events] == ["log", "log"]
    assert events[0]["message"] == ytdlp_worker.PROTOCOL_SMOKE_TITLE
    assert events[1]["message"] == "WARNING: 字幕 ❤️ Русская музыка العربية"


def test_worker_protocol_survives_cp1252_environment_with_all_unicode_classes():
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(PROJECT_ROOT / "src"), existing_pythonpath) if part
    )
    environment["PYTHONUTF8"] = "0"
    environment["PYTHONIOENCODING"] = "cp1252"

    completed = subprocess.run(
        [sys.executable, "-m", "neural_extractor_v3.core.ytdlp_worker"],
        input=json.dumps({"mode": "protocol_smoke"}).encode("utf-8"),
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=environment,
        shell=False,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0
    assert b"UnicodeEncodeError" not in completed.stderr
    assert completed.stderr == b""
    events = _parse_protocol_frames(completed.stdout)
    assert len(events) == 2
    assert [event["sequence"] for event in events] == [0, 1]
    for event in events:
        assert event["title"] == ytdlp_worker.PROTOCOL_SMOKE_TITLE
        assert "｜" in event["title"]
        assert event["subtitle_destination"].endswith("夜の名曲.srt")
        assert "❤️" in event["emoji"]
        assert event["cjk"] == "日本語 中文 한국어"
        assert event["cyrillic"] == "Русская музыка"
        assert event["arabic"] == "الموسيقى العربية"
        assert event["combining"] == "Cafe\u0301"
        assert len(event["long_windows_path"]) > 260
