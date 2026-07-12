from __future__ import annotations

import pytest
from neural_extractor_v3.core import downloader as downloader_module
from neural_extractor_v3.core.auth import (
    AuthResolution,
    AuthStrategy,
    BrowserCookieSource,
    CookieFileStatus,
)
from neural_extractor_v3.core.downloader import (
    AUDIO_M4A_SELECTOR,
    AUDIO_MP3_SELECTOR,
    DEFAULT_YOUTUBE_CLIENTS,
    MAX_DOWNLOAD_ATTEMPTS,
    VIDEO_MP4_SELECTOR,
    DownloadEngine,
    YtdlpCapturedOutput,
    YtdlpRunError,
    YtdlpRunResult,
    recover_stale_download_processes,
)
from neural_extractor_v3.core.js_runtime import JavaScriptRuntimeStatus
from neural_extractor_v3.core.youtube_errors import FailureCategory
from neural_extractor_v3.models import (
    DownloadJob,
    DownloadOptions,
    MediaMode,
    PlaylistMode,
)

PUBLIC_VIDEO_TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def _mock_runtime(monkeypatch, tmp_path, *, found=True):
    path = tmp_path / "node.exe" if found else None
    monkeypatch.setattr(
        downloader_module,
        "ensure_youtube_js_runtime",
        lambda: JavaScriptRuntimeStatus(
            found=found,
            name="node" if found else "",
            path=path,
            version="v22.17.0" if found else "",
        ),
    )


def _resolution(tmp_path, *, cookie=True, browsers=("chrome", "edge", "brave", "firefox")):
    strategies = [AuthStrategy("none", "no authentication", {}, attempted_auth=False)]
    cookie_path = tmp_path / "cookies.txt" if cookie else None
    messages = []
    if cookie_path:
        cookie_path.write_text(
            "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tFALSE\t0\tSID\tsecret\n",
            encoding="utf-8",
        )
        strategies.append(
            AuthStrategy(
                "cookies_file",
                "cookies.txt",
                {"cookiefile": str(cookie_path)},
                attempted_auth=True,
            )
        )
        messages.append("cookies.txt available: cookies.txt (held for authenticated fallback)")
    else:
        messages.append("cookies.txt not loaded")

    sources = []
    for browser in browsers:
        display = browser.title()
        source = BrowserCookieSource(browser, display, tmp_path / display)
        sources.append(source)
        strategies.append(
            AuthStrategy(
                "browser",
                display,
                {"cookiesfrombrowser": (browser,)},
                attempted_auth=True,
            )
        )
    if sources:
        messages.append(
            "browser cookie fallback available: "
            + ", ".join(source.display_name for source in sources)
        )
    status = CookieFileStatus(
        cookie_path,
        bool(cookie_path),
        "cookies.txt contains YouTube/Google cookies" if cookie_path else "cookies.txt not loaded",
    )
    return AuthResolution(
        strategies=strategies,
        messages=messages,
        cookie_file_status=status,
        browser_source=sources[0] if sources else None,
        browser_sources=sources,
    )


def _mock_resolution(monkeypatch, resolution):
    monkeypatch.setattr(
        downloader_module,
        "resolve_auth_strategies",
        lambda _cookie_file: resolution,
    )


def _engine(tmp_path, **overrides):
    options = DownloadOptions(output_dir=tmp_path, **overrides)
    return DownloadEngine(options)


def _auth_id(options):
    if options.get("cookiefile"):
        return "cookies.txt"
    if options.get("cookiesfrombrowser"):
        return options["cookiesfrombrowser"][0]
    return "none"


def _clients(options):
    return tuple(options["extractor_args"]["youtube"]["player_client"])


def _error(message, options, *, category_hint=None, phase="download"):
    return YtdlpRunError(
        "yt-dlp <redacted>",
        YtdlpCapturedOutput(stderr=[message]),
        exit_code=1,
        phase=phase,
        format_selector=str(options.get("format") or ""),
        player_clients=_clients(options),
        category_hint=category_hint,
    )


def test_public_video_first_attempt_uses_no_cookies_even_when_cookie_file_exists(
    tmp_path, monkeypatch
):
    _mock_runtime(monkeypatch, tmp_path)
    resolution = _resolution(tmp_path)
    _mock_resolution(monkeypatch, resolution)
    calls = []
    logs = []

    def succeed(self, url, options, *, discover_only=False):
        calls.append((_auth_id(options), discover_only))
        return YtdlpRunResult()

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", succeed)
    engine = DownloadEngine(
        DownloadOptions(output_dir=tmp_path, cookie_file=resolution.cookie_file_status.path),
        log_callback=logs.append,
    )

    result = engine.download(DownloadJob(PUBLIC_VIDEO_TEST_URL))

    assert result.success
    assert calls == [("none", False)]
    assert any("cookies.txt available" in log for log in logs)
    assert not any("Using cookies.txt" in log for log in logs)
    assert any("auth=none" in log for log in logs)


def test_authentication_specific_failure_enables_cookie_file_fallback(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    resolution = _resolution(tmp_path, browsers=())
    _mock_resolution(monkeypatch, resolution)
    calls = []

    def auth_then_success(self, url, options, *, discover_only=False):
        calls.append(_auth_id(options))
        if len(calls) == 1:
            raise _error("ERROR: Sign in to confirm your age. Use --cookies", options)
        return YtdlpRunResult()

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", auth_then_success)

    result = _engine(tmp_path, cookie_file=resolution.cookie_file_status.path).download(
        DownloadJob(PUBLIC_VIDEO_TEST_URL)
    )

    assert result.success
    assert calls == ["none", "cookies.txt"]


def test_generic_http_403_never_triggers_cookie_or_browser_fallback(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    resolution = _resolution(tmp_path)
    _mock_resolution(monkeypatch, resolution)
    calls = []

    def always_403(self, url, options, *, discover_only=False):
        calls.append((_auth_id(options), discover_only, _clients(options)))
        raise _error(
            "ERROR: unable to download video data: HTTP Error 403: Forbidden",
            options,
        )

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", always_403)

    result = _engine(tmp_path, cookie_file=resolution.cookie_file_status.path).download(
        DownloadJob(PUBLIC_VIDEO_TEST_URL)
    )

    assert not result.success
    assert result.failure_category == FailureCategory.HTTP_403_MEDIA_REJECTED.value
    assert all(call[0] == "none" for call in calls)
    assert calls[0][2] == DEFAULT_YOUTUBE_CLIENTS
    assert len(calls) == 3  # primary, one clean retry, one bounded alternative discovery


def test_cookie_file_http_403_is_not_repeated_and_browser_fallback_is_controlled(
    tmp_path, monkeypatch
):
    _mock_runtime(monkeypatch, tmp_path)
    resolution = _resolution(tmp_path, browsers=("chrome",))
    _mock_resolution(monkeypatch, resolution)
    calls = []

    def run(self, url, options, *, discover_only=False):
        auth = _auth_id(options)
        calls.append(auth)
        if auth == "none":
            raise _error("ERROR: Login required. Use --cookies", options)
        if auth == "cookies.txt":
            raise _error(
                "ERROR: unable to download video data: HTTP Error 403: Forbidden",
                options,
            )
        return YtdlpRunResult()

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", run)

    result = _engine(tmp_path, cookie_file=resolution.cookie_file_status.path).download(
        DownloadJob(PUBLIC_VIDEO_TEST_URL)
    )

    assert result.success
    assert calls == ["none", "cookies.txt", "chrome"]


def test_chrome_cookie_lock_disables_chrome_for_remainder_of_job(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    resolution = _resolution(tmp_path, cookie=False, browsers=("chrome", "firefox"))
    _mock_resolution(monkeypatch, resolution)
    calls = []

    def run(self, url, options, *, discover_only=False):
        auth = _auth_id(options)
        calls.append(auth)
        if auth == "none":
            raise _error("ERROR: Sign in to confirm you're not a bot. Use --cookies", options)
        if auth == "chrome":
            raise _error("ERROR: Could not copy Chrome cookie database", options)
        return YtdlpRunResult()

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", run)

    result = _engine(tmp_path).download(DownloadJob(PUBLIC_VIDEO_TEST_URL))

    assert result.success
    assert calls == ["none", "chrome", "firefox"]
    assert calls.count("chrome") == 1


def test_dpapi_failure_disables_provider_without_node_guidance(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    resolution = _resolution(tmp_path, cookie=False, browsers=("edge", "brave"))
    _mock_resolution(monkeypatch, resolution)
    calls = []
    logs = []

    def run(self, url, options, *, discover_only=False):
        auth = _auth_id(options)
        calls.append(auth)
        if auth == "none":
            raise _error("ERROR: Login required. Use --cookies", options)
        if auth == "edge":
            raise _error("ERROR: Failed to decrypt cookies with Windows DPAPI", options)
        return YtdlpRunResult()

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", run)
    engine = DownloadEngine(DownloadOptions(output_dir=tmp_path), log_callback=logs.append)

    result = engine.download(DownloadJob(PUBLIC_VIDEO_TEST_URL))

    assert result.success
    assert calls == ["none", "edge", "brave"]
    assert not any("install node" in log.lower() for log in logs)
    assert not any("solver unavailable" in log.lower() for log in logs)


def test_authenticated_browser_order_is_bounded_deterministic_and_unique(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    resolution = _resolution(tmp_path)
    _mock_resolution(monkeypatch, resolution)
    calls = []

    def always_auth_failure(self, url, options, *, discover_only=False):
        calls.append(_auth_id(options))
        raise _error("ERROR: Login required. Use --cookies", options)

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", always_auth_failure)

    result = _engine(tmp_path, cookie_file=resolution.cookie_file_status.path).download(
        DownloadJob(PUBLIC_VIDEO_TEST_URL)
    )

    assert not result.success
    assert calls == ["none", "cookies.txt", "chrome", "edge", "brave", "firefox"]
    assert len(calls) == MAX_DOWNLOAD_ATTEMPTS
    assert len(calls) == len(set(calls))


def test_inactivity_timeout_starts_one_clean_no_cookie_retry(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    resolution = _resolution(tmp_path, cookie=False, browsers=())
    _mock_resolution(monkeypatch, resolution)
    calls = []

    def timeout_then_success(self, url, options, *, discover_only=False):
        calls.append(_auth_id(options))
        if len(calls) == 1:
            raise _error(
                "Network inactivity timeout",
                options,
                category_hint=FailureCategory.NETWORK_INACTIVITY_TIMEOUT,
            )
        return YtdlpRunResult()

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", timeout_then_success)

    result = _engine(tmp_path).download(DownloadJob(PUBLIC_VIDEO_TEST_URL))

    assert result.success
    assert calls == ["none", "none"]


def test_cancel_stops_new_attempts_and_returns_typed_result(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    resolution = _resolution(tmp_path)
    _mock_resolution(monkeypatch, resolution)
    calls = []

    def cancel_on_first(self, url, options, *, discover_only=False):
        calls.append(_auth_id(options))
        self.cancel()
        raise _error(
            "ERROR: unable to download video data: HTTP Error 403: Forbidden",
            options,
        )

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", cancel_on_first)

    result = _engine(tmp_path).download(DownloadJob(PUBLIC_VIDEO_TEST_URL))

    assert not result.success
    assert result.message == "Download cancelled"
    assert result.failure_category == FailureCategory.DOWNLOAD_CANCELLED.value
    assert calls == ["none"]


def test_format_discovery_selects_only_actual_available_ids(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    resolution = _resolution(tmp_path, cookie=False, browsers=())
    _mock_resolution(monkeypatch, resolution)
    downloads = []
    discoveries = []

    def run(self, url, options, *, discover_only=False):
        if discover_only:
            discoveries.append(str(options["format"]))
            return YtdlpRunResult(
                formats=[
                    {"format_id": "137", "ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": 1080},
                    {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "abr": 128},
                ]
            )
        downloads.append(str(options["format"]))
        if len(downloads) == 1:
            raise _error("ERROR: Requested format is not available", options, phase="preflight")
        return YtdlpRunResult()

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", run)

    result = _engine(tmp_path).download(DownloadJob(PUBLIC_VIDEO_TEST_URL))

    assert result.success
    assert downloads == [VIDEO_MP4_SELECTOR, "137+140"]
    assert discoveries == [VIDEO_MP4_SELECTOR]
    assert "best" not in downloads[1]


def test_image_only_discovery_does_not_start_media_fallback(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    resolution = _resolution(tmp_path, cookie=False, browsers=())
    _mock_resolution(monkeypatch, resolution)
    downloads = []

    def run(self, url, options, *, discover_only=False):
        if discover_only:
            return YtdlpRunResult(
                formats=[
                    {"format_id": "storyboard", "ext": "mhtml", "vcodec": "none", "acodec": "none"}
                ]
            )
        downloads.append(str(options["format"]))
        raise _error("ERROR: Requested format is not available", options, phase="preflight")

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", run)

    result = _engine(tmp_path).download(DownloadJob(PUBLIC_VIDEO_TEST_URL))

    assert not result.success
    assert result.failure_category == FailureCategory.ONLY_IMAGE_FORMATS_AVAILABLE.value
    assert downloads == [VIDEO_MP4_SELECTOR]


def test_po_token_warning_stops_without_unsafe_workaround(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    resolution = _resolution(tmp_path)
    _mock_resolution(monkeypatch, resolution)
    calls = []

    def fail(self, url, options, *, discover_only=False):
        calls.append(_auth_id(options))
        raise _error("WARNING: This client requires a PO Token for video playback", options)

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", fail)

    result = _engine(tmp_path).download(DownloadJob(PUBLIC_VIDEO_TEST_URL))

    assert not result.success
    assert result.failure_category == FailureCategory.PO_TOKEN_REQUIRED.value
    assert calls == ["none"]


def test_node_found_plus_n_challenge_never_reports_missing_node(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path, found=True)
    resolution = _resolution(tmp_path, cookie=False, browsers=())
    _mock_resolution(monkeypatch, resolution)

    def fail(self, url, options, *, discover_only=False):
        raise _error("WARNING: n challenge solving failed", options)

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", fail)

    result = _engine(tmp_path).download(DownloadJob(PUBLIC_VIDEO_TEST_URL))

    assert not result.success
    assert result.failure_category == FailureCategory.UNKNOWN.value
    assert "unavailable" not in result.message.lower()


def test_genuine_missing_runtime_stops_before_attempt(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path, found=False)
    resolution = _resolution(tmp_path, cookie=False, browsers=())
    _mock_resolution(monkeypatch, resolution)

    def should_not_run(*args, **kwargs):
        raise AssertionError("yt-dlp must not start without the required runtime")

    monkeypatch.setattr(DownloadEngine, "_run_yt_dlp", should_not_run)

    result = _engine(tmp_path).download(DownloadJob(PUBLIC_VIDEO_TEST_URL))

    assert not result.success
    assert result.failure_category == FailureCategory.JAVASCRIPT_RUNTIME_UNAVAILABLE.value
    assert "Install Node.js" in result.message


def test_video_quality_generates_height_limited_selector(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    options = _engine(tmp_path, quality="1080p Full HD").build_ydl_options(PUBLIC_VIDEO_TEST_URL)

    assert "height<=1080" in options["format"]
    assert options["merge_output_format"] == "mp4"


def test_mp3_m4a_subtitles_and_thumbnail_options_are_preserved(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    mp3 = _engine(
        tmp_path,
        media_mode=MediaMode.AUDIO_MP3,
        thumbnail=True,
        embed_thumbnail=True,
    ).build_ydl_options(PUBLIC_VIDEO_TEST_URL)
    m4a = _engine(tmp_path, media_mode=MediaMode.AUDIO_M4A).build_ydl_options(
        PUBLIC_VIDEO_TEST_URL
    )
    subtitles = _engine(
        tmp_path,
        media_mode=MediaMode.SUBTITLES_ONLY,
        subtitle_language="nl",
        subtitles=True,
    ).build_ydl_options(PUBLIC_VIDEO_TEST_URL)

    assert mp3["format"] == AUDIO_MP3_SELECTOR
    assert {item["key"] for item in mp3["postprocessors"]} >= {
        "FFmpegExtractAudio",
        "EmbedThumbnail",
    }
    assert m4a["format"] == AUDIO_M4A_SELECTOR
    assert "merge_output_format" not in m4a
    assert subtitles["skip_download"] is True
    assert subtitles["subtitleslangs"] == ["nl"]


def test_mix_url_normalizes_to_current_video_only_and_command_has_no_playlist(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    logs = []
    engine = DownloadEngine(
        DownloadOptions(output_dir=tmp_path, playlist_mode=PlaylistMode.FULL),
        log_callback=logs.append,
    )
    prepared = engine.prepare_url(
        "https://www.youtube.com/watch?v=abc123&list=RDabc123&start_radio=1"
    )
    options = engine.build_ydl_options(prepared)
    command = engine._yt_dlp_command(prepared, options)

    assert prepared == "https://www.youtube.com/watch?v=abc123"
    assert options["noplaylist"] is True
    assert "--no-playlist" in command
    assert "--yes-playlist" not in command
    assert "--playlist-end" not in command
    assert logs == ["YouTube Mix detected. Downloading current video only."]


def test_auth_options_merge_without_overwriting_selected_client(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    auth = AuthStrategy(
        "browser",
        "Firefox",
        {"cookiesfrombrowser": ("firefox",)},
        attempted_auth=True,
    )
    engine = _engine(tmp_path)
    profile = engine._profile(
        auth,
        player_clients=("web",),
        reason="authenticated_fallback",
    )

    options = engine._options_for_attempt_profile(PUBLIC_VIDEO_TEST_URL, profile)

    assert options["cookiesfrombrowser"] == ("firefox",)
    assert _clients(options) == ("web",)


def test_command_and_logs_redact_cookie_path_and_secret_values(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    cookie_path = tmp_path / "cookies.txt"
    engine = _engine(tmp_path, cookie_file=cookie_path)
    auth = AuthStrategy(
        "cookies_file",
        "cookies.txt",
        {"cookiefile": str(cookie_path)},
        attempted_auth=True,
    )
    options = engine.build_ydl_options(PUBLIC_VIDEO_TEST_URL, auth)

    command = engine._yt_dlp_command(PUBLIC_VIDEO_TEST_URL, options)
    cleaned = engine._redact_diagnostic_text(
        f"cookie=super-secret authorization=token path={cookie_path}"
    )

    assert "--cookies <cookies.txt>" in command
    assert str(cookie_path) not in command
    assert "super-secret" not in cleaned
    assert "authorization=token" not in cleaned


def test_public_video_test_url_is_normal_video_url():
    assert PUBLIC_VIDEO_TEST_URL == "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def test_attempt_temp_is_isolated_and_stale_owner_state_is_cleaned(tmp_path, monkeypatch):
    _mock_runtime(monkeypatch, tmp_path)
    app_data = tmp_path / "app-data"
    monkeypatch.setattr(downloader_module, "app_data_dir", lambda: app_data)
    engine = _engine(tmp_path)

    active = engine._create_attempt_temp()
    (active / "worker.tmp").write_text("isolated", encoding="utf-8")
    engine._cleanup_attempt_temp(active)

    stale = app_data / "worker-temp" / "owner-99999999-controlled"
    stale.mkdir(parents=True)
    (stale / "leftover.tmp").write_text("stale", encoding="utf-8")
    monkeypatch.setattr(downloader_module, "is_process_running", lambda _pid: False)

    messages = recover_stale_download_processes()

    assert not active.exists()
    assert not stale.exists()
    assert any("Removed stale" in message for message in messages)


@pytest.mark.parametrize("mode", [MediaMode.VIDEO, MediaMode.AUDIO_MP3, MediaMode.AUDIO_M4A])
def test_media_modes_keep_remote_ejs_and_node_runtime(tmp_path, monkeypatch, mode):
    _mock_runtime(monkeypatch, tmp_path)

    options = _engine(tmp_path, media_mode=mode).build_ydl_options(PUBLIC_VIDEO_TEST_URL)

    assert options["remote_components"] == ["ejs:github"]
    assert options["js_runtimes"]["node"]["path"].endswith("node.exe")
