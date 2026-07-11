import sys
from pathlib import Path

from neural_extractor_v3.config import YTDLP_SOCKET_TIMEOUT_SECONDS
from neural_extractor_v3.core import downloader as downloader_module
from neural_extractor_v3.core.auth import AuthResolution, AuthStrategy, CookieFileStatus
from neural_extractor_v3.core.downloader import (
    AUDIO_M4A_SELECTOR,
    AUDIO_MP3_SELECTOR,
    BEST_VIDEO_SELECTOR,
    HTTP_403_FINAL_MESSAGE,
    HTTP_403_MAX_ATTEMPTS,
    PROGRESSIVE_VIDEO_SELECTOR,
    VIDEO_MP4_SELECTOR,
    DownloadEngine,
    YtdlpCapturedOutput,
    YtdlpRunError,
)
from neural_extractor_v3.core.js_runtime import (
    MISSING_CHALLENGE_SOLVER_COMPONENT_MESSAGE,
    MISSING_JS_RUNTIME_MESSAGE,
    JavaScriptRuntimeStatus,
    is_youtube_challenge_component_error,
    is_youtube_challenge_runtime_error,
)
from neural_extractor_v3.models import DownloadJob, DownloadOptions, MediaMode, PlaylistMode

PUBLIC_VIDEO_TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def make_engine(tmp_path: Path, **overrides) -> DownloadEngine:
    options = DownloadOptions(output_dir=tmp_path, **overrides)
    return DownloadEngine(options)


def _mock_runtime(
    monkeypatch,
    *,
    found: bool = True,
    path: Path | None = None,
) -> JavaScriptRuntimeStatus:
    status = JavaScriptRuntimeStatus(
        found=found,
        name="node" if found else "",
        path=path,
        version="v22.17.0" if found else "",
    )
    monkeypatch.setattr(downloader_module, "ensure_youtube_js_runtime", lambda: status)
    return status


def _mock_auth(monkeypatch) -> None:
    resolution = AuthResolution(
        strategies=[
            AuthStrategy(
                kind="none",
                display_name="no authentication",
                ydl_options={},
                attempted_auth=False,
            )
        ],
        messages=[],
        cookie_file_status=CookieFileStatus(None, False, "cookies.txt not loaded"),
        browser_source=None,
        browser_sources=[],
    )
    monkeypatch.setattr(downloader_module, "resolve_auth_strategies", lambda _cookie_file: resolution)


def _mock_cookie_and_browser_auth(
    monkeypatch,
    tmp_path: Path,
    browsers: tuple[str, ...] = ("edge",),
) -> Path:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tFALSE\t0\tSID\tsecret-value\n",
        encoding="utf-8",
    )
    strategies = [
        AuthStrategy(
            kind="cookies_file",
            display_name="cookies.txt",
            attempted_auth=True,
            ydl_options={
                "cookiefile": str(cookie_file),
                "extractor_args": {"youtube": {"player_client": ["default"]}},
            },
        )
    ]
    for browser in browsers:
        strategies.append(
            AuthStrategy(
                kind="browser",
                display_name=browser.title(),
                attempted_auth=True,
                ydl_options={
                    "cookiesfrombrowser": (browser,),
                    "extractor_args": {"youtube": {"player_client": ["default"]}},
                },
            )
        )
    strategies.append(
        AuthStrategy(
            kind="none",
            display_name="no authentication",
            attempted_auth=False,
            ydl_options={},
        )
    )
    resolution = AuthResolution(
        strategies=strategies,
        messages=[],
        cookie_file_status=CookieFileStatus(cookie_file, True, "valid"),
        browser_source=None,
        browser_sources=[],
    )
    monkeypatch.setattr(downloader_module, "resolve_auth_strategies", lambda _cookie_file: resolution)
    return cookie_file


def _attempt_key(ydl_opts) -> tuple[str, str, tuple[str, ...]]:
    if ydl_opts.get("cookiefile"):
        auth = "cookies.txt"
    elif ydl_opts.get("cookiesfrombrowser"):
        auth = str(ydl_opts["cookiesfrombrowser"][0])
    else:
        auth = "none"
    clients = tuple(ydl_opts["extractor_args"]["youtube"]["player_client"])
    return auth, str(ydl_opts["format"]), clients


def _raise_media_http_403(engine, prepared_url, ydl_opts) -> None:
    output = YtdlpCapturedOutput(
        stderr=["ERROR: unable to download video data: HTTP Error 403: Forbidden"]
    )
    raise YtdlpRunError(
        engine._yt_dlp_command(prepared_url, ydl_opts),
        output,
        exit_code=1,
        phase="download",
        format_selector=str(ydl_opts["format"]),
        player_clients=tuple(ydl_opts["extractor_args"]["youtube"]["player_client"]),
    )


def test_video_quality_generates_height_limited_selector(tmp_path):
    engine = make_engine(tmp_path, media_mode=MediaMode.VIDEO, quality="1080p Full HD")
    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123")

    assert "bv*[height<=1080][ext=mp4]+ba[ext=m4a]" in opts["format"]
    assert opts["format"].endswith("bv*+ba/b")
    assert opts["merge_output_format"] == "mp4"
    assert opts["noplaylist"] is True
    assert opts["socket_timeout"] == YTDLP_SOCKET_TIMEOUT_SECONDS


def test_youtube_js_runtime_is_passed_to_yt_dlp_options_and_command(tmp_path, monkeypatch):
    node_path = tmp_path / "node.exe"
    _mock_runtime(monkeypatch, path=node_path)
    engine = make_engine(tmp_path)

    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123")
    command = engine._yt_dlp_command("https://www.youtube.com/watch?v=abc123", opts)

    assert opts["js_runtimes"] == {"node": {"path": str(node_path)}}
    assert opts["remote_components"] == ["ejs:github"]
    assert "--js-runtimes" in command
    assert "node:" in command
    assert str(node_path) in command
    assert "--remote-components ejs:github" in command


def test_missing_youtube_js_runtime_stops_media_download_cleanly(tmp_path, monkeypatch):
    logs: list[str] = []
    _mock_runtime(monkeypatch, found=False)
    _mock_auth(monkeypatch)

    def fail_run(self, prepared_url, ydl_opts):
        raise AssertionError("yt-dlp should not run without a YouTube JS runtime")

    monkeypatch.setattr(downloader_module.DownloadEngine, "_run_yt_dlp", fail_run)

    engine = DownloadEngine(DownloadOptions(output_dir=tmp_path), log_callback=logs.append)
    result = engine.download(DownloadJob("https://www.youtube.com/watch?v=abc123"))

    assert not result.success
    assert result.message == MISSING_JS_RUNTIME_MESSAGE
    assert "JavaScript runtime for YouTube challenge: not found" in logs


def test_n_challenge_error_is_not_retried_as_format_fallback(tmp_path, monkeypatch):
    node_path = tmp_path / "node.exe"
    _mock_runtime(monkeypatch, path=node_path)
    _mock_auth(monkeypatch)
    calls: list[str] = []

    def fail_with_n_challenge(self, prepared_url, ydl_opts):
        calls.append(ydl_opts["format"])
        output = YtdlpCapturedOutput(
            stderr=[
                "WARNING: [youtube] n challenge solving failed",
                "WARNING: Only images are available for download",
                "ERROR: Requested format is not available",
            ]
        )
        raise YtdlpRunError("yt-dlp", output, exit_code=1)

    monkeypatch.setattr(downloader_module.DownloadEngine, "_run_yt_dlp", fail_with_n_challenge)

    engine = make_engine(tmp_path)
    result = engine.download(DownloadJob("https://www.youtube.com/watch?v=abc123"))

    assert is_youtube_challenge_runtime_error(
        "WARNING: [youtube] n challenge solving failed\nWARNING: Only images are available"
    )
    assert not result.success
    assert result.message == MISSING_JS_RUNTIME_MESSAGE
    assert calls == [VIDEO_MP4_SELECTOR]


def test_missing_challenge_component_is_not_retried_as_format_fallback(tmp_path, monkeypatch):
    node_path = tmp_path / "node.exe"
    _mock_runtime(monkeypatch, path=node_path)
    _mock_auth(monkeypatch)
    calls: list[str] = []

    def fail_with_missing_component(self, prepared_url, ydl_opts):
        calls.append(ydl_opts["format"])
        output = YtdlpCapturedOutput(
            stderr=[
                "WARNING: Remote component challenge solver script was skipped. "
                "Enable downloads with --remote-components ejs:github.",
                "ERROR: Requested format is not available",
            ]
        )
        raise YtdlpRunError("yt-dlp", output, exit_code=1)

    monkeypatch.setattr(downloader_module.DownloadEngine, "_run_yt_dlp", fail_with_missing_component)

    engine = make_engine(tmp_path)
    result = engine.download(DownloadJob("https://www.youtube.com/watch?v=abc123"))

    assert is_youtube_challenge_component_error("remote component challenge solver script was skipped")
    assert not result.success
    assert result.message == MISSING_CHALLENGE_SOLVER_COMPONENT_MESSAGE
    assert calls == [VIDEO_MP4_SELECTOR]


def test_plain_format_error_still_retries_with_remote_components_enabled(tmp_path, monkeypatch):
    node_path = tmp_path / "node.exe"
    _mock_runtime(monkeypatch, path=node_path)
    _mock_auth(monkeypatch)
    calls: list[str] = []

    def format_unavailable_once(self, prepared_url, ydl_opts):
        calls.append(ydl_opts["format"])
        if len(calls) == 1:
            output = YtdlpCapturedOutput(stderr=["ERROR: Requested format is not available"])
            command = self._yt_dlp_command(prepared_url, ydl_opts)
            raise YtdlpRunError(command, output, exit_code=1)

    monkeypatch.setattr(downloader_module.DownloadEngine, "_run_yt_dlp", format_unavailable_once)

    engine = make_engine(tmp_path)
    result = engine.download(DownloadJob("https://www.youtube.com/watch?v=abc123"))

    assert result.success
    assert calls == [VIDEO_MP4_SELECTOR, BEST_VIDEO_SELECTOR]


def test_media_http_403_retries_with_browser_cookies_and_stops_on_success(
    tmp_path,
    monkeypatch,
):
    logs: list[str] = []
    _mock_runtime(monkeypatch, path=tmp_path / "node.exe")
    cookie_file = _mock_cookie_and_browser_auth(monkeypatch, tmp_path, ("edge", "firefox"))
    calls: list[tuple[str, str, tuple[str, ...]]] = []

    def fail_cookie_file_then_succeed(self, prepared_url, ydl_opts):
        calls.append(_attempt_key(ydl_opts))
        if len(calls) == 1:
            _raise_media_http_403(self, prepared_url, ydl_opts)

    monkeypatch.setattr(
        downloader_module.DownloadEngine,
        "_run_yt_dlp",
        fail_cookie_file_then_succeed,
    )

    engine = DownloadEngine(
        DownloadOptions(output_dir=tmp_path, cookie_file=cookie_file),
        log_callback=logs.append,
    )
    result = engine.download(DownloadJob("https://www.youtube.com/watch?v=abc123"))

    assert result.success
    assert calls == [
        ("cookies.txt", VIDEO_MP4_SELECTOR, ("default",)),
        ("edge", VIDEO_MP4_SELECTOR, ("default",)),
    ]
    assert "HTTP 403 with cookies.txt. Retrying with browser cookies from Edge." in logs
    assert not any(PROGRESSIVE_VIDEO_SELECTOR in log for log in logs)


def test_http_403_browser_cookie_extraction_failure_skips_to_next_browser(
    tmp_path,
    monkeypatch,
):
    logs: list[str] = []
    _mock_runtime(monkeypatch, path=tmp_path / "node.exe")
    cookie_file = _mock_cookie_and_browser_auth(monkeypatch, tmp_path, ("chrome", "edge"))
    calls: list[tuple[str, str, tuple[str, ...]]] = []

    def fail_cookie_then_skip_locked_chrome(self, prepared_url, ydl_opts):
        calls.append(_attempt_key(ydl_opts))
        if len(calls) == 1:
            _raise_media_http_403(self, prepared_url, ydl_opts)
        if ydl_opts.get("cookiesfrombrowser") == ("chrome",):
            raise YtdlpRunError(
                "yt-dlp",
                YtdlpCapturedOutput(stderr=["ERROR: Could not copy Chrome cookie database"]),
                exit_code=1,
                phase="preflight",
            )

    monkeypatch.setattr(
        downloader_module.DownloadEngine,
        "_run_yt_dlp",
        fail_cookie_then_skip_locked_chrome,
    )

    engine = DownloadEngine(
        DownloadOptions(output_dir=tmp_path, cookie_file=cookie_file),
        log_callback=logs.append,
    )
    result = engine.download(DownloadJob("https://www.youtube.com/watch?v=abc123"))

    assert result.success
    assert [call[0] for call in calls] == ["cookies.txt", "chrome", "edge"]
    assert any("cookie extraction failure" in log for log in logs)


def test_non_403_after_cascade_start_does_not_reenter_outer_auth_loop(
    tmp_path,
    monkeypatch,
):
    _mock_runtime(monkeypatch, path=tmp_path / "node.exe")
    cookie_file = _mock_cookie_and_browser_auth(monkeypatch, tmp_path, ("edge",))
    calls: list[tuple[str, str, tuple[str, ...]]] = []

    def fail_with_403_then_auth(self, prepared_url, ydl_opts):
        call = _attempt_key(ydl_opts)
        calls.append(call)
        if call[1] == PROGRESSIVE_VIDEO_SELECTOR:
            raise YtdlpRunError(
                "yt-dlp",
                YtdlpCapturedOutput(stderr=["ERROR: Sign in to confirm you're not a bot"]),
                exit_code=1,
                phase="preflight",
                format_selector=call[1],
                player_clients=call[2],
            )
        _raise_media_http_403(self, prepared_url, ydl_opts)

    monkeypatch.setattr(
        downloader_module.DownloadEngine,
        "_run_yt_dlp",
        fail_with_403_then_auth,
    )

    result = DownloadEngine(
        DownloadOptions(output_dir=tmp_path, cookie_file=cookie_file)
    ).download(DownloadJob("https://www.youtube.com/watch?v=abc123"))

    assert not result.success
    assert calls == [
        ("cookies.txt", VIDEO_MP4_SELECTOR, ("default",)),
        ("edge", VIDEO_MP4_SELECTOR, ("default",)),
        ("cookies.txt", PROGRESSIVE_VIDEO_SELECTOR, ("default",)),
    ]


def test_http_403_cascade_is_bounded_unique_and_reports_final_error_once(
    tmp_path,
    monkeypatch,
):
    logs: list[str] = []
    _mock_runtime(monkeypatch, path=tmp_path / "node.exe")
    browsers = ("chrome", "edge", "brave", "firefox")
    cookie_file = _mock_cookie_and_browser_auth(monkeypatch, tmp_path, browsers)
    calls: list[tuple[str, str, tuple[str, ...]]] = []

    def always_403(self, prepared_url, ydl_opts):
        calls.append(_attempt_key(ydl_opts))
        _raise_media_http_403(self, prepared_url, ydl_opts)

    monkeypatch.setattr(downloader_module.DownloadEngine, "_run_yt_dlp", always_403)

    engine = DownloadEngine(
        DownloadOptions(output_dir=tmp_path, cookie_file=cookie_file),
        log_callback=logs.append,
    )
    result = engine.download(DownloadJob("https://www.youtube.com/watch?v=abc123"))

    assert not result.success
    assert result.message == HTTP_403_FINAL_MESSAGE
    assert len(calls) == HTTP_403_MAX_ATTEMPTS
    assert len(set(calls)) == len(calls)
    assert [call[0] for call in calls] == [
        "cookies.txt",
        "chrome",
        "edge",
        "brave",
        "firefox",
        "cookies.txt",
        "cookies.txt",
        "cookies.txt",
    ]
    assert [call[1] for call in calls[-3:]] == [
        PROGRESSIVE_VIDEO_SELECTOR,
        PROGRESSIVE_VIDEO_SELECTOR,
        PROGRESSIVE_VIDEO_SELECTOR,
    ]
    assert [call[2] for call in calls[-3:]] == [("default",), ("mweb",), ("web",)]
    assert sum(log.startswith("HTTP 403 diagnostics:") for log in logs) == 1
    assert HTTP_403_FINAL_MESSAGE not in logs
    assert "secret-value" not in "\n".join(logs)


def test_duplicate_http_403_profiles_are_not_retried(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, path=tmp_path / "node.exe")
    _mock_auth(monkeypatch)
    monkeypatch.setattr(
        downloader_module,
        "HTTP_403_CLIENT_FALLBACKS",
        (("mweb", "default"), ("mweb", "default"), ("web",)),
    )
    calls: list[tuple[str, str, tuple[str, ...]]] = []

    def always_403(self, prepared_url, ydl_opts):
        calls.append(_attempt_key(ydl_opts))
        _raise_media_http_403(self, prepared_url, ydl_opts)

    monkeypatch.setattr(downloader_module.DownloadEngine, "_run_yt_dlp", always_403)

    result = make_engine(tmp_path).download(
        DownloadJob("https://www.youtube.com/watch?v=abc123")
    )

    assert not result.success
    assert calls == [
        ("none", VIDEO_MP4_SELECTOR, ("mweb", "default")),
        ("none", PROGRESSIVE_VIDEO_SELECTOR, ("mweb", "default")),
        ("none", PROGRESSIVE_VIDEO_SELECTOR, ("web",)),
    ]


def test_non_403_and_preflight_403_do_not_start_media_retry_cascade(
    tmp_path,
    monkeypatch,
):
    _mock_runtime(monkeypatch, path=tmp_path / "node.exe")
    _mock_auth(monkeypatch)

    for phase, message in (
        ("download", "ERROR: network connection timed out"),
        ("preflight", "ERROR: unable to download video data: HTTP Error 403: Forbidden"),
    ):
        logs: list[str] = []
        calls: list[str] = []

        def fail_once(self, prepared_url, ydl_opts, *, _phase=phase, _message=message):
            calls.append(str(ydl_opts["format"]))
            raise YtdlpRunError(
                "yt-dlp",
                YtdlpCapturedOutput(stderr=[_message]),
                exit_code=1,
                phase=_phase,
                format_selector=str(ydl_opts["format"]),
            )

        monkeypatch.setattr(downloader_module.DownloadEngine, "_run_yt_dlp", fail_once)
        engine = DownloadEngine(DownloadOptions(output_dir=tmp_path), log_callback=logs.append)
        result = engine.download(DownloadJob("https://www.youtube.com/watch?v=abc123"))

        assert not result.success
        assert calls == [VIDEO_MP4_SELECTOR]
        assert not any("HTTP 403 retry attempt" in log for log in logs)


def test_cancel_stops_http_403_cascade_before_next_profile(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, path=tmp_path / "node.exe")
    _mock_auth(monkeypatch)
    calls: list[str] = []

    def cancel_on_first_403(self, prepared_url, ydl_opts):
        calls.append(str(ydl_opts["format"]))
        self.cancel()
        _raise_media_http_403(self, prepared_url, ydl_opts)

    monkeypatch.setattr(
        downloader_module.DownloadEngine,
        "_run_yt_dlp",
        cancel_on_first_403,
    )

    result = make_engine(tmp_path).download(
        DownloadJob("https://www.youtube.com/watch?v=abc123")
    )

    assert not result.success
    assert result.message == "Download cancelled by user"
    assert calls == [VIDEO_MP4_SELECTOR]


def test_successful_primary_download_never_uses_progressive_403_fallback(
    tmp_path,
    monkeypatch,
):
    _mock_runtime(monkeypatch, path=tmp_path / "node.exe")
    _mock_auth(monkeypatch)
    calls: list[str] = []

    def succeed(self, prepared_url, ydl_opts):
        calls.append(str(ydl_opts["format"]))

    monkeypatch.setattr(downloader_module.DownloadEngine, "_run_yt_dlp", succeed)

    result = make_engine(tmp_path).download(
        DownloadJob("https://www.youtube.com/watch?v=abc123")
    )

    assert result.success
    assert calls == [VIDEO_MP4_SELECTOR]


def test_mp3_mode_extracts_audio_and_embeds_thumbnail(tmp_path):
    engine = make_engine(
        tmp_path,
        media_mode=MediaMode.AUDIO_MP3,
        thumbnail=True,
        embed_thumbnail=True,
        audio_quality="320",
    )
    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123")
    post_keys = [processor["key"] for processor in opts["postprocessors"]]

    assert opts["format"] == AUDIO_MP3_SELECTOR
    assert "merge_output_format" not in opts
    assert "FFmpegExtractAudio" in post_keys
    assert "EmbedThumbnail" in post_keys
    assert opts["writethumbnail"] is True


def test_m4a_mode_prefers_m4a_audio_without_mp4_merge(tmp_path):
    engine = make_engine(tmp_path, media_mode=MediaMode.AUDIO_M4A)
    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123")

    assert opts["format"] == AUDIO_M4A_SELECTOR
    assert "merge_output_format" not in opts


def test_subtitle_mode_writes_srt_and_skips_media(tmp_path):
    engine = make_engine(
        tmp_path,
        media_mode=MediaMode.SUBTITLES_ONLY,
        subtitle_language="nl",
        subtitles=True,
    )
    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123")
    post_keys = [processor["key"] for processor in opts["postprocessors"]]

    assert opts["skip_download"] is True
    assert opts["subtitleslangs"] == ["nl"]
    assert opts["subtitlesformat"].startswith("srt")
    assert "FFmpegSubtitlesConvertor" in post_keys


def test_full_playlist_keeps_playlist_enabled(tmp_path):
    engine = make_engine(tmp_path, playlist_mode=PlaylistMode.FULL)
    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123&list=PL42")

    assert opts["noplaylist"] is False
    assert "%(playlist" in opts["outtmpl"]


def test_full_mode_without_playlist_keeps_single_video(tmp_path):
    engine = make_engine(tmp_path, playlist_mode=PlaylistMode.FULL)
    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123")

    assert opts["noplaylist"] is True


def test_mix_url_normalizes_to_single_video_and_logs(tmp_path):
    logs: list[str] = []
    engine = DownloadEngine(
        DownloadOptions(output_dir=tmp_path, playlist_mode=PlaylistMode.FULL),
        log_callback=logs.append,
    )

    prepared_url = engine.prepare_url(
        "https://www.youtube.com/watch?v=abc123&list=RDabc123&start_radio=1"
    )
    opts = engine.build_ydl_options(prepared_url)
    command = engine._yt_dlp_command(prepared_url, opts)

    assert prepared_url == "https://www.youtube.com/watch?v=abc123"
    assert opts["noplaylist"] is True
    assert "playlistend" not in opts
    assert "--no-playlist" in command
    assert "--yes-playlist" not in command
    assert "--playlist-end" not in command
    assert logs == ["YouTube Mix detected. Downloading current video only."]


def test_best_video_uses_mp4_selector(tmp_path):
    engine = make_engine(tmp_path, media_mode=MediaMode.VIDEO, quality="Best available")
    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123")

    assert opts["format"] == VIDEO_MP4_SELECTOR


def test_auth_strategy_is_merged_into_ydl_options(tmp_path):
    engine = make_engine(tmp_path)
    auth = AuthStrategy(
        kind="browser",
        display_name="Chrome",
        attempted_auth=True,
        ydl_options={
            "cookiesfrombrowser": ("chrome",),
            "extractor_args": {"youtube": {"player_client": ["default"]}},
        },
    )

    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123", auth)

    assert opts["cookiesfrombrowser"] == ("chrome",)
    assert opts["extractor_args"] == {"youtube": {"player_client": ["default"]}}


def test_yt_dlp_failure_includes_command_stdout_stderr_and_exit_code(tmp_path, monkeypatch):
    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts
            opts["logger"].debug("[debug] stdout from logger")
            opts["logger"].warning("warning from logger")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download=False):
            print("stdout line one")
            print("stderr line one", file=sys.stderr)
            self.opts["logger"].error("ERROR: Requested format is not available")
            return {"id": "abc123"}

        def download(self, urls):
            print("stdout line two")
            print("stderr line two", file=sys.stderr)
            return 1

    monkeypatch.setattr(downloader_module.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    engine = make_engine(tmp_path)
    opts = engine.build_ydl_options(
        "https://www.youtube.com/watch?v=abc123",
        AuthStrategy(
            kind="cookies_file",
            display_name="cookies.txt",
            ydl_options={"cookiefile": str(tmp_path / "cookies.txt")},
            attempted_auth=True,
        ),
    )

    try:
        engine._run_yt_dlp("https://www.youtube.com/watch?v=abc123", opts)
    except YtdlpRunError as exc:
        message = exc.full_text()
    else:
        raise AssertionError("Expected YtdlpRunError")

    assert "Exit code: 1" in message
    assert "yt-dlp command:" in message
    assert "yt-dlp stdout:" in message
    assert "yt-dlp output:" in message
    assert "--cookies <cookies.txt>" in message
    assert str(tmp_path / "cookies.txt") not in message
    assert "stdout line one" in message
    assert "stdout line two" in message
    assert "stderr line one" in message
    assert "stderr line two" in message
    assert "ERROR: Requested format is not available" in message
    assert "WARNING: warning from logger" in message


def test_user_result_is_concise_while_activity_log_keeps_ytdlp_diagnostics(
    tmp_path,
    monkeypatch,
):
    logs: list[str] = []
    _mock_runtime(monkeypatch, path=tmp_path / "node.exe")
    _mock_auth(monkeypatch)

    def fail_with_diagnostics(self, prepared_url, ydl_opts):
        raise YtdlpRunError(
            self._yt_dlp_command(prepared_url, ydl_opts),
            YtdlpCapturedOutput(stderr=["ERROR: media fragment failed during test"]),
            exit_code=1,
            phase="download",
        )

    monkeypatch.setattr(
        downloader_module.DownloadEngine,
        "_run_yt_dlp",
        fail_with_diagnostics,
    )
    engine = DownloadEngine(DownloadOptions(output_dir=tmp_path), log_callback=logs.append)

    result = engine.download(DownloadJob("https://www.youtube.com/watch?v=abc123"))

    assert not result.success
    assert result.message == "Download failed: ERROR: media fragment failed during test"
    assert "yt-dlp command" not in result.message
    assert any("yt-dlp command:" in entry for entry in logs)


def test_http_403_final_message_matches_clean_support_guidance():
    assert HTTP_403_FINAL_MESSAGE == (
        "YouTube rejected the media download with HTTP 403. "
        "Try refreshing cookies, using browser cookies, updating Neural Extractor, "
        "or lowering format quality."
    )


def test_clean_error_message_removes_yt_dlp_github_links(tmp_path):
    engine = make_engine(tmp_path)
    message = engine._clean_error_message(
        "ERROR: Something failed. Please report this issue at "
        "https://github.com/yt-dlp/yt-dlp/issues?q=abc"
    )

    assert "github.com/yt-dlp" not in message
    assert message == "ERROR: Something failed."


def test_public_video_test_url_is_normal_video_url():
    assert PUBLIC_VIDEO_TEST_URL == "https://www.youtube.com/watch?v=jNQXAC9IVRw"
