"""yt-dlp powered download engine for Neural Extractor V3."""

from __future__ import annotations

import contextlib
import io
import re
import subprocess
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yt_dlp

from neural_extractor_v3.config import (
    QUALITY_PRESETS,
    THROTTLE_SAFE_OPTIONS,
    YOUTUBE_REMOTE_COMPONENTS,
    bin_dir,
)
from neural_extractor_v3.core.auth import (
    AuthResolution,
    AuthStrategy,
    clean_authentication_error,
    clean_browser_cookie_extraction_error,
    clean_live_event_ended_error,
    is_authentication_error,
    is_browser_cookie_extraction_error,
    is_live_event_ended_error,
    resolve_auth_strategies,
)
from neural_extractor_v3.core.js_runtime import (
    clean_youtube_challenge_component_error,
    clean_youtube_challenge_runtime_error,
    ensure_youtube_js_runtime,
    is_youtube_challenge_component_error,
    is_youtube_challenge_runtime_error,
)
from neural_extractor_v3.core.subtitles import subtitle_postprocessor, subtitle_ydl_options
from neural_extractor_v3.models import (
    DownloadJob,
    DownloadOptions,
    DownloadResult,
    MediaMode,
    PlaylistMode,
    ProgressEvent,
)
from neural_extractor_v3.utils import (
    format_bytes_per_second,
    format_eta,
    is_youtube_mix_url,
    is_youtube_url,
    normalize_single_video_url,
    normalize_user_url,
    should_download_playlist,
)

ProgressCallback = Callable[[ProgressEvent], None]
LogCallback = Callable[[str], None]

VIDEO_MP4_SELECTOR = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
AUDIO_M4A_SELECTOR = "ba[ext=m4a]/ba/bestaudio"
AUDIO_MP3_SELECTOR = "ba/bestaudio"
BEST_VIDEO_SELECTOR = "bv*+ba/b"
PROGRESSIVE_VIDEO_SELECTOR = "b[ext=mp4]/best[ext=mp4]/best"
HTTP_403_MAX_ATTEMPTS = 8
HTTP_403_CLIENT_FALLBACKS = (("mweb",), ("web",))
HTTP_403_FINAL_MESSAGE = (
    "YouTube rejected the media download with HTTP 403. "
    "Try refreshing cookies, using browser cookies, updating Neural Extractor, "
    "or lowering format quality."
)
FORMAT_UNAVAILABLE_RETRY_MESSAGE = (
    "Requested format is not available for this video. "
    "Retrying with best compatible format."
)


class DownloadCancelledError(RuntimeError):
    """Raised when a download is cancelled by the user."""


@dataclass(slots=True)
class YtdlpCapturedOutput:
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)

    def stdout_text(self) -> str:
        return "\n".join(line for line in self.stdout if line).strip()

    def stderr_text(self) -> str:
        return "\n".join(line for line in self.stderr if line).strip()


@dataclass(frozen=True, slots=True)
class DownloadAttemptProfile:
    """Sanitized, finite yt-dlp profile used by the HTTP 403 cascade."""

    auth_strategy: AuthStrategy
    format_selector: str
    player_clients: tuple[str, ...]
    node_runtime_available: bool
    remote_ejs_enabled: bool
    reason: str = "primary"

    def key(self) -> tuple[str, str, str, tuple[str, ...], bool, bool]:
        return (
            self.auth_strategy.kind,
            self.auth_strategy.display_name,
            self.format_selector,
            self.player_clients,
            self.node_runtime_available,
            self.remote_ejs_enabled,
        )


@dataclass(frozen=True, slots=True)
class Http403RetryOutcome:
    recovered: bool
    attempts: int
    browser_fallback_attempted: bool
    final_error: YtdlpRunError | None
    final_profile: DownloadAttemptProfile


class YtdlpCaptureLogger:
    """Collect yt-dlp logger output as stdout/stderr equivalents."""

    def __init__(self, output: YtdlpCapturedOutput) -> None:
        self.output = output

    def debug(self, message: str) -> None:
        if message:
            self.output.stdout.append(str(message))

    def warning(self, message: str) -> None:
        if message:
            self.output.stderr.append(f"WARNING: {message}")

    def error(self, message: str) -> None:
        if message:
            self.output.stderr.append(str(message))


class YtdlpRunError(RuntimeError):
    """Raised with complete yt-dlp command/output diagnostics."""

    def __init__(
        self,
        command: str,
        output: YtdlpCapturedOutput,
        exit_code: int | None = None,
        cause: BaseException | None = None,
        phase: str = "unknown",
        format_selector: str = "",
        player_clients: tuple[str, ...] = (),
    ) -> None:
        self.command = command
        self.output = output
        self.exit_code = exit_code
        self.cause = cause
        self.phase = phase
        self.format_selector = format_selector
        self.player_clients = player_clients
        super().__init__(self.full_text())

    def full_text(self) -> str:
        sections = ["Download failed."]
        if self.exit_code is not None:
            sections.append(f"Exit code: {self.exit_code}")
        if self.phase != "unknown":
            sections.append(f"Failure phase: {self.phase}")

        sections.append(f"yt-dlp command:\n{self.command}")
        sections.append(f"yt-dlp stdout:\n{self.output.stdout_text() or '<empty>'}")
        sections.append(f"yt-dlp output:\n{self.output.stderr_text() or '<empty>'}")

        if self.cause is not None:
            cause_text = "".join(
                traceback.format_exception(type(self.cause), self.cause, self.cause.__traceback__)
            ).strip()
            sections.append(f"Python exception:\n{cause_text}")

        return "\n\n".join(sections)


def _player_clients_from_options(ydl_opts: dict[str, Any]) -> tuple[str, ...]:
    extractor_args = ydl_opts.get("extractor_args") or {}
    youtube_args = extractor_args.get("youtube") or {}
    player_clients = youtube_args.get("player_client") or ()
    if isinstance(player_clients, str):
        return tuple(client.strip() for client in player_clients.split(",") if client.strip())
    return tuple(str(client) for client in player_clients if client)


def _is_media_http_403_error(error: YtdlpRunError | str) -> bool:
    """Return True only for a 403 tied to the actual media-download phase."""
    if isinstance(error, YtdlpRunError):
        if error.phase == "preflight":
            return False
        error_text = error.full_text()
    else:
        error_text = str(error)

    lowered = error_text.lower()
    if "http error 403" not in lowered:
        return False
    media_markers = (
        "unable to download video data",
        "unable to download media",
        "[download] got error",
    )
    return any(marker in lowered for marker in media_markers)


def _height_limited_video_selector(height: int) -> str:
    return (
        f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
        f"b[height<={height}][ext=mp4]/"
        f"bv*[height<={height}]+ba/"
        f"b[height<={height}]/"
        "bv*+ba/b"
    )


def _is_unavailable_format_error(error_text: str) -> bool:
    if is_youtube_challenge_component_error(error_text) or is_youtube_challenge_runtime_error(error_text):
        return False

    lowered = error_text.lower()
    patterns = (
        "requested format is not available",
        "requested format not available",
        "format is not available",
        "use --list-formats",
        "no suitable formats",
    )
    return any(pattern in lowered for pattern in patterns)


class DownloadEngine:
    """Builds yt-dlp options and runs download jobs."""

    def __init__(
        self,
        options: DownloadOptions,
        progress_callback: ProgressCallback | None = None,
        log_callback: LogCallback | None = None,
    ) -> None:
        self.options = options
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.cancel_requested = False
        self._active_job_id = ""
        self._files_seen: list[Path] = []
        self.js_runtime_status = ensure_youtube_js_runtime()

    def cancel(self) -> None:
        self.cancel_requested = True

    def download(self, job: DownloadJob) -> DownloadResult:
        self._active_job_id = job.job_id
        self._files_seen = []

        if not is_youtube_url(job.url):
            return DownloadResult(job.job_id, False, f"Invalid YouTube URL: {job.url}")

        url = self.prepare_url(job.url)
        self.options.output_dir.mkdir(parents=True, exist_ok=True)
        auth_resolution = resolve_auth_strategies(self.options.cookie_file)

        self._log(self.js_runtime_status.diagnostic)
        if self._media_download_requires_js_runtime() and not self.js_runtime_status.found:
            message = clean_youtube_challenge_runtime_error()
            self._log(message)
            return DownloadResult(job.job_id, False, message, self._files_seen)

        for message in auth_resolution.messages:
            self._log(message)

        last_auth_error = ""
        browser_cookie_error = ""
        for index, auth_strategy in enumerate(auth_resolution.strategies):
            try:
                self._log(f"Starting {self.options.media_mode.label}: {url}")
                self._log_auth_strategy(auth_strategy, retry=index > 0)
                self._download_with_strategy(url, auth_strategy)
                break
            except DownloadCancelledError:
                return DownloadResult(job.job_id, False, "Download cancelled by user", self._files_seen)
            except YtdlpRunError as exc:
                error_text = exc.full_text()
                http_403_cascade_started = False
                if self._should_retry_media_http_403(url, exc):
                    http_403_cascade_started = True
                    initial_profile = self._profile_from_error(url, auth_strategy, exc)
                    self._log(
                        "Download attempt 1 result: HTTP 403; "
                        f"{self._attempt_profile_summary(initial_profile)}; "
                        f"yt-dlp: {self._yt_dlp_error_summary(exc)}"
                    )
                    try:
                        outcome = self._retry_media_http_403(
                            url,
                            auth_resolution,
                            initial_profile,
                            exc,
                        )
                    except DownloadCancelledError:
                        return DownloadResult(
                            job.job_id,
                            False,
                            "Download cancelled by user",
                            self._files_seen,
                        )
                    except YtdlpRunError as retry_error:
                        exc = retry_error
                        error_text = retry_error.full_text()
                    else:
                        if outcome.recovered:
                            break
                        self._log_http_403_final_diagnostics(initial_profile, outcome)
                        return DownloadResult(
                            job.job_id,
                            False,
                            HTTP_403_FINAL_MESSAGE,
                            self._files_seen,
                        )

                self._log(error_text)
                if is_youtube_challenge_component_error(error_text):
                    message = clean_youtube_challenge_component_error()
                    self._log(message)
                    return DownloadResult(
                        job.job_id,
                        False,
                        message,
                        self._files_seen,
                    )
                if is_youtube_challenge_runtime_error(error_text):
                    message = clean_youtube_challenge_runtime_error()
                    self._log(message)
                    return DownloadResult(
                        job.job_id,
                        False,
                        message,
                        self._files_seen,
                    )
                if is_live_event_ended_error(error_text):
                    self._log(clean_live_event_ended_error())
                    return DownloadResult(
                        job.job_id,
                        False,
                        clean_live_event_ended_error(),
                        self._files_seen,
                    )
                if is_browser_cookie_extraction_error(error_text):
                    browser_cookie_error = error_text
                    self._log(self._browser_cookie_failure_log(auth_strategy))
                    if not http_403_cascade_started and self._has_browser_cookie_retry(
                        auth_resolution, index
                    ):
                        continue
                    return DownloadResult(
                        job.job_id,
                        False,
                        clean_browser_cookie_extraction_error(),
                        self._files_seen,
                    )
                if is_authentication_error(error_text):
                    last_auth_error = error_text
                    self._log(self._auth_failure_log(auth_strategy))
                    if not http_403_cascade_started and self._has_auth_retry(
                        auth_resolution, index
                    ):
                        continue
                    return DownloadResult(
                        job.job_id,
                        False,
                        clean_authentication_error(self._auth_was_attempted(auth_resolution)),
                        self._files_seen,
                    )
                return DownloadResult(
                    job.job_id,
                    False,
                    f"Download failed: {self._yt_dlp_error_summary(exc)}",
                    self._files_seen,
                )
            except Exception as exc:
                error_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
                self._log(error_text)
                return DownloadResult(
                    job.job_id,
                    False,
                    f"Download failed: {self._clean_error_message(str(exc))}",
                    self._files_seen,
                )
        else:
            return DownloadResult(
                job.job_id,
                False,
                clean_authentication_error(self._auth_was_attempted(auth_resolution))
                if last_auth_error
                else clean_browser_cookie_extraction_error()
                if browser_cookie_error
                else "Download failed before yt-dlp could start.",
                self._files_seen,
            )

        message = "Download completed"
        if self._files_seen:
            message = f"Download completed: {self._files_seen[-1].name}"
        return DownloadResult(job.job_id, True, message, self._files_seen)

    def prepare_url(self, url: str) -> str:
        normalized_url = normalize_user_url(url)
        if is_youtube_mix_url(normalized_url):
            self._log("YouTube Mix detected. Downloading current video only.")
            return normalize_single_video_url(normalized_url)
        if self.options.playlist_mode == PlaylistMode.SINGLE:
            return normalize_single_video_url(normalized_url)
        return normalized_url

    def build_ydl_options(
        self,
        url: str,
        auth_strategy: AuthStrategy | None = None,
    ) -> dict[str, Any]:
        playlist = should_download_playlist(url, self.options.playlist_mode.value)
        outtmpl = self._output_template(playlist)
        postprocessors = self._postprocessors()

        opts: dict[str, Any] = {
            "outtmpl": outtmpl,
            "format": self._format_selector(),
            "ignoreerrors": playlist,
            "noplaylist": not playlist,
            "no_warnings": False,
            "quiet": False,
            "noprogress": True,
            "windowsfilenames": True,
            "restrictfilenames": self.options.restrict_filenames,
            "overwrites": self.options.overwrite,
            "continuedl": True,
            "progress_hooks": [self._progress_hook],
            "extractor_args": {"youtube": {"player_client": ["mweb", "default"]}},
            **THROTTLE_SAFE_OPTIONS,
        }

        if self.options.media_mode == MediaMode.VIDEO:
            opts["merge_output_format"] = "mp4"

        js_runtimes = self.js_runtime_status.ytdlp_options()
        if js_runtimes:
            opts["js_runtimes"] = js_runtimes
        if YOUTUBE_REMOTE_COMPONENTS:
            opts["remote_components"] = list(YOUTUBE_REMOTE_COMPONENTS)

        local_bin = bin_dir()
        if local_bin.exists():
            opts["ffmpeg_location"] = str(local_bin)

        if auth_strategy:
            opts.update(auth_strategy.ydl_options)

        if self.options.media_mode in {MediaMode.THUMBNAIL_ONLY, MediaMode.SUBTITLES_ONLY}:
            opts["skip_download"] = True

        if self.options.thumbnail or self.options.media_mode == MediaMode.THUMBNAIL_ONLY:
            opts["writethumbnail"] = True
            opts["convertthumbnails"] = "jpg"

        if self.options.metadata_json:
            opts["writeinfojson"] = True

        if self.options.subtitles or self.options.media_mode == MediaMode.SUBTITLES_ONLY:
            opts.update(
                subtitle_ydl_options(
                    language=self.options.subtitle_language,
                    include_automatic=self.options.auto_subtitles,
                )
            )

        if postprocessors:
            opts["postprocessors"] = postprocessors

        return opts

    def _download_with_strategy(
        self,
        prepared_url: str,
        auth_strategy: AuthStrategy,
    ) -> None:
        ydl_opts = self.build_ydl_options(prepared_url, auth_strategy=auth_strategy)
        self._log(f"selected format selector: {ydl_opts['format']}")
        self._log(
            "Download attempt profile: "
            f"{self._attempt_profile_summary(self._profile_from_options(auth_strategy, ydl_opts))}"
        )
        try:
            self._run_yt_dlp(prepared_url, ydl_opts)
        except YtdlpRunError as exc:
            error_text = exc.full_text()
            if (
                is_youtube_challenge_component_error(error_text)
                or is_youtube_challenge_runtime_error(error_text)
                or not _is_unavailable_format_error(error_text)
            ):
                raise

            fallback_selector = self._fallback_format_selector()
            if fallback_selector == ydl_opts["format"]:
                raise

            self._log(exc.full_text())
            self._log(FORMAT_UNAVAILABLE_RETRY_MESSAGE)
            fallback_opts = dict(ydl_opts)
            fallback_opts["format"] = fallback_selector
            self._log(f"selected format selector: {fallback_selector}")
            self._run_yt_dlp(prepared_url, fallback_opts)

    def _should_retry_media_http_403(
        self,
        prepared_url: str,
        error: YtdlpRunError,
    ) -> bool:
        if not self._media_download_requires_js_runtime():
            return False
        if should_download_playlist(prepared_url, self.options.playlist_mode.value):
            return False
        return _is_media_http_403_error(error)

    def _profile_from_options(
        self,
        auth_strategy: AuthStrategy,
        ydl_opts: dict[str, Any],
        reason: str = "primary",
    ) -> DownloadAttemptProfile:
        return DownloadAttemptProfile(
            auth_strategy=auth_strategy,
            format_selector=str(ydl_opts.get("format") or self._format_selector()),
            player_clients=_player_clients_from_options(ydl_opts) or ("default",),
            node_runtime_available=self.js_runtime_status.found,
            remote_ejs_enabled="ejs:github" in YOUTUBE_REMOTE_COMPONENTS,
            reason=reason,
        )

    def _profile_from_error(
        self,
        prepared_url: str,
        auth_strategy: AuthStrategy,
        error: YtdlpRunError,
    ) -> DownloadAttemptProfile:
        ydl_opts = self.build_ydl_options(prepared_url, auth_strategy)
        if error.format_selector:
            ydl_opts["format"] = error.format_selector
        if error.player_clients:
            extractor_args = dict(ydl_opts.get("extractor_args") or {})
            youtube_args = dict(extractor_args.get("youtube") or {})
            youtube_args["player_client"] = list(error.player_clients)
            extractor_args["youtube"] = youtube_args
            ydl_opts["extractor_args"] = extractor_args
        return self._profile_from_options(auth_strategy, ydl_opts)

    def _http_403_retry_profiles(
        self,
        resolution: AuthResolution,
        initial_profile: DownloadAttemptProfile,
    ) -> list[DownloadAttemptProfile]:
        candidates: list[DownloadAttemptProfile] = []

        if initial_profile.auth_strategy.is_cookie_file:
            for strategy in resolution.strategies:
                if strategy.is_browser:
                    candidates.append(
                        DownloadAttemptProfile(
                            auth_strategy=strategy,
                            format_selector=initial_profile.format_selector,
                            player_clients=initial_profile.player_clients,
                            node_runtime_available=initial_profile.node_runtime_available,
                            remote_ejs_enabled=initial_profile.remote_ejs_enabled,
                            reason="browser",
                        )
                    )

        fallback_selector = self._http_403_format_fallback_selector(
            initial_profile.format_selector
        )
        candidates.append(
            DownloadAttemptProfile(
                auth_strategy=initial_profile.auth_strategy,
                format_selector=fallback_selector,
                player_clients=initial_profile.player_clients,
                node_runtime_available=initial_profile.node_runtime_available,
                remote_ejs_enabled=initial_profile.remote_ejs_enabled,
                reason="progressive",
            )
        )

        for player_clients in HTTP_403_CLIENT_FALLBACKS:
            candidates.append(
                DownloadAttemptProfile(
                    auth_strategy=initial_profile.auth_strategy,
                    format_selector=fallback_selector,
                    player_clients=player_clients,
                    node_runtime_available=initial_profile.node_runtime_available,
                    remote_ejs_enabled=initial_profile.remote_ejs_enabled,
                    reason="client",
                )
            )

        seen = {initial_profile.key()}
        unique_profiles: list[DownloadAttemptProfile] = []
        for profile in candidates:
            if profile.key() in seen:
                continue
            seen.add(profile.key())
            unique_profiles.append(profile)

        return unique_profiles[: HTTP_403_MAX_ATTEMPTS - 1]

    def _retry_media_http_403(
        self,
        prepared_url: str,
        resolution: AuthResolution,
        initial_profile: DownloadAttemptProfile,
        initial_error: YtdlpRunError,
    ) -> Http403RetryOutcome:
        profiles = self._http_403_retry_profiles(resolution, initial_profile)
        last_error = initial_error
        last_profile = initial_profile
        attempts = 1
        browser_fallback_attempted = False

        for attempt_number, profile in enumerate(profiles, start=2):
            if self.cancel_requested:
                raise DownloadCancelledError

            attempts = attempt_number
            last_profile = profile
            browser_fallback_attempted = (
                browser_fallback_attempted or profile.auth_strategy.is_browser
            )
            self._log_http_403_retry_reason(profile)
            self._log(
                f"HTTP 403 retry attempt {attempt_number}/{HTTP_403_MAX_ATTEMPTS}: "
                f"{self._attempt_profile_summary(profile)}"
            )
            ydl_opts = self._options_for_attempt_profile(prepared_url, profile)

            try:
                self._run_yt_dlp(prepared_url, ydl_opts)
            except DownloadCancelledError:
                raise
            except YtdlpRunError as exc:
                summary = self._yt_dlp_error_summary(exc)
                if _is_media_http_403_error(exc):
                    last_error = exc
                    self._log(
                        f"HTTP 403 retry attempt {attempt_number} result: HTTP 403; "
                        f"yt-dlp: {summary}"
                    )
                    continue
                if profile.auth_strategy.is_browser and is_browser_cookie_extraction_error(
                    exc.full_text()
                ):
                    self._log(
                        f"HTTP 403 retry attempt {attempt_number} result: "
                        f"cookie extraction failure; yt-dlp: {summary}"
                    )
                    continue
                if profile.auth_strategy.is_browser and is_authentication_error(exc.full_text()):
                    self._log(
                        f"HTTP 403 retry attempt {attempt_number} result: "
                        f"authentication failure; yt-dlp: {summary}"
                    )
                    continue
                self._log(
                    f"HTTP 403 retry attempt {attempt_number} result: another non-403 failure; "
                    f"yt-dlp: {summary}"
                )
                raise
            else:
                self._log(f"HTTP 403 retry attempt {attempt_number} result: success")
                return Http403RetryOutcome(
                    recovered=True,
                    attempts=attempts,
                    browser_fallback_attempted=browser_fallback_attempted,
                    final_error=None,
                    final_profile=profile,
                )

        return Http403RetryOutcome(
            recovered=False,
            attempts=attempts,
            browser_fallback_attempted=browser_fallback_attempted,
            final_error=last_error,
            final_profile=last_profile,
        )

    def _options_for_attempt_profile(
        self,
        prepared_url: str,
        profile: DownloadAttemptProfile,
    ) -> dict[str, Any]:
        ydl_opts = self.build_ydl_options(prepared_url, profile.auth_strategy)
        ydl_opts["format"] = profile.format_selector
        extractor_args = dict(ydl_opts.get("extractor_args") or {})
        youtube_args = dict(extractor_args.get("youtube") or {})
        youtube_args["player_client"] = list(profile.player_clients)
        extractor_args["youtube"] = youtube_args
        ydl_opts["extractor_args"] = extractor_args
        return ydl_opts

    def _http_403_format_fallback_selector(self, current_selector: str) -> str:
        if self.options.media_mode == MediaMode.VIDEO:
            return PROGRESSIVE_VIDEO_SELECTOR
        return current_selector

    def _log_http_403_retry_reason(self, profile: DownloadAttemptProfile) -> None:
        if profile.reason == "browser":
            self._log(
                "HTTP 403 with cookies.txt. Retrying with browser cookies from "
                f"{profile.auth_strategy.display_name}."
            )
        elif profile.reason == "progressive":
            self._log(
                "HTTP 403 on adaptive media formats. "
                "Retrying with a progressive/best format fallback."
            )
        elif profile.reason == "client":
            clients = ",".join(profile.player_clients)
            self._log(f"HTTP 403 retry using YouTube client profile: {clients}.")

    def _attempt_profile_summary(self, profile: DownloadAttemptProfile) -> str:
        if profile.auth_strategy.is_cookie_file:
            auth_source = "cookies.txt"
        elif profile.auth_strategy.is_browser:
            auth_source = f"browser:{profile.auth_strategy.display_name}"
        else:
            auth_source = "none"
        player_clients = ",".join(profile.player_clients) or "default"
        node_state = "found" if profile.node_runtime_available else "not found"
        ejs_state = "enabled" if profile.remote_ejs_enabled else "disabled"
        return (
            f"auth={auth_source}; format={profile.format_selector}; "
            f"client={player_clients}; node={node_state}; remote EJS={ejs_state}"
        )

    def _yt_dlp_error_summary(self, error: YtdlpRunError) -> str:
        candidates = [line.strip() for line in error.output.stderr if line.strip()]
        summary = next(
            (
                line
                for line in reversed(candidates)
                if "error" in line.lower() or "forbidden" in line.lower()
            ),
            candidates[-1] if candidates else str(error.cause or "yt-dlp failed"),
        )
        if self.options.cookie_file:
            summary = summary.replace(str(self.options.cookie_file), "<cookies.txt>")
        home = str(Path.home())
        if home:
            summary = summary.replace(home, "<user-profile>")
        summary = re.sub(
            r"(?i)\b(cookie|authorization)\s*[:=]\s*\S+",
            r"\1=<redacted>",
            summary,
        )
        summary = re.sub(r"(https?://[^\s?]+)\?\S+", r"\1?<redacted>", summary)
        return " ".join(summary.split())[:500] or "yt-dlp failed"

    def _log_http_403_final_diagnostics(
        self,
        initial_profile: DownloadAttemptProfile,
        outcome: Http403RetryOutcome,
    ) -> None:
        final_error = outcome.final_error
        final_summary = self._yt_dlp_error_summary(final_error) if final_error else "HTTP 403"
        browser_state = "yes" if outcome.browser_fallback_attempted else "no"
        cookies_state = "yes" if initial_profile.auth_strategy.is_cookie_file else "no"
        clients = ",".join(outcome.final_profile.player_clients) or "default"
        node_state = "found" if outcome.final_profile.node_runtime_available else "not found"
        ejs_state = "enabled" if outcome.final_profile.remote_ejs_enabled else "disabled"
        self._log(
            "HTTP 403 diagnostics: "
            f"attempts={outcome.attempts}/{HTTP_403_MAX_ATTEMPTS}; "
            f"cookies.txt used={cookies_state}; browser fallback attempted={browser_state}; "
            f"final format={outcome.final_profile.format_selector}; final client={clients}; "
            f"node={node_state}; remote EJS={ejs_state}; "
            f"final yt-dlp exception={final_summary}"
        )

    def _run_yt_dlp(
        self,
        prepared_url: str,
        ydl_opts: dict[str, Any],
    ) -> None:
        playlist = should_download_playlist(prepared_url, self.options.playlist_mode.value)
        command = self._yt_dlp_command(prepared_url, ydl_opts)
        self._log(f"yt-dlp command:\n{command}")

        output = YtdlpCapturedOutput()
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        run_opts = dict(ydl_opts)
        run_opts["logger"] = YtdlpCaptureLogger(output)
        phase = "download" if playlist else "preflight"
        format_selector = str(ydl_opts.get("format") or "")
        player_clients = _player_clients_from_options(ydl_opts)

        try:
            with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(
                captured_stderr
            ):
                with yt_dlp.YoutubeDL(run_opts) as ydl:
                    if not playlist:
                        # Explicit preflight uses the same YoutubeDL instance and auth options as final download.
                        ydl.extract_info(prepared_url, download=False)
                    phase = "download"
                    retcode = ydl.download([prepared_url])
        except DownloadCancelledError:
            raise
        except Exception as exc:
            self._append_redirected_output(output, captured_stdout, captured_stderr)
            raise YtdlpRunError(
                command=command,
                output=output,
                exit_code=1,
                cause=exc,
                phase=phase,
                format_selector=format_selector,
                player_clients=player_clients,
            ) from exc

        self._append_redirected_output(output, captured_stdout, captured_stderr)
        if retcode:
            raise YtdlpRunError(
                command=command,
                output=output,
                exit_code=int(retcode),
                phase="download",
                format_selector=format_selector,
                player_clients=player_clients,
            )

    def _append_redirected_output(
        self,
        output: YtdlpCapturedOutput,
        captured_stdout: io.StringIO,
        captured_stderr: io.StringIO,
    ) -> None:
        stdout_text = captured_stdout.getvalue().strip()
        stderr_text = captured_stderr.getvalue().strip()
        if stdout_text:
            output.stdout.extend(stdout_text.splitlines())
        if stderr_text:
            output.stderr.extend(stderr_text.splitlines())

    def _yt_dlp_command(self, url: str, ydl_opts: dict[str, Any]) -> str:
        args = ["yt-dlp"]

        def add_option(flag: str, value: Any) -> None:
            if value is not None:
                args.extend([flag, str(value)])

        add_option("-f", ydl_opts.get("format"))
        add_option("-o", ydl_opts.get("outtmpl"))
        add_option("--merge-output-format", ydl_opts.get("merge_output_format"))

        if ydl_opts.get("noplaylist"):
            args.append("--no-playlist")
        else:
            args.append("--yes-playlist")
        if ydl_opts.get("ignoreerrors"):
            args.append("--ignore-errors")
        if ydl_opts.get("noprogress"):
            args.append("--no-progress")
        if ydl_opts.get("windowsfilenames"):
            args.append("--windows-filenames")
        if ydl_opts.get("restrictfilenames"):
            args.append("--restrict-filenames")
        if ydl_opts.get("overwrites"):
            args.append("--force-overwrites")
        if ydl_opts.get("continuedl"):
            args.append("--continue")

        add_option("--sleep-interval", ydl_opts.get("sleep_interval"))
        add_option("--max-sleep-interval", ydl_opts.get("max_sleep_interval"))
        add_option("--sleep-requests", ydl_opts.get("sleep_interval_requests"))
        add_option("--sleep-subtitles", ydl_opts.get("sleep_interval_subtitles"))
        add_option("--socket-timeout", ydl_opts.get("socket_timeout"))
        add_option("--retries", ydl_opts.get("retries"))
        add_option("--fragment-retries", ydl_opts.get("fragment_retries"))
        add_option("--extractor-retries", ydl_opts.get("extractor_retries"))
        add_option("--throttled-rate", ydl_opts.get("throttled_rate"))
        add_option("--playlist-end", ydl_opts.get("playlistend"))

        extractor_args = ydl_opts.get("extractor_args") or {}
        youtube_args = extractor_args.get("youtube") or {}
        player_clients = youtube_args.get("player_client")
        if player_clients:
            add_option("--extractor-args", f"youtube:player_client={','.join(player_clients)}")

        if ydl_opts.get("ffmpeg_location"):
            add_option("--ffmpeg-location", ydl_opts["ffmpeg_location"])
        if ydl_opts.get("cookiefile"):
            add_option("--cookies", "<cookies.txt>")
        if ydl_opts.get("cookiesfrombrowser"):
            browser = ydl_opts["cookiesfrombrowser"][0]
            add_option("--cookies-from-browser", browser)
        if ydl_opts.get("js_runtimes"):
            js_runtimes = ydl_opts["js_runtimes"]
            runtime_args = []
            for name, config in js_runtimes.items():
                path = config.get("path") if isinstance(config, dict) else None
                runtime_args.append(f"{name}:{path}" if path else str(name))
            add_option("--js-runtimes", ",".join(runtime_args))
        if ydl_opts.get("remote_components"):
            for component in ydl_opts["remote_components"]:
                add_option("--remote-components", component)

        if ydl_opts.get("skip_download"):
            args.append("--skip-download")
        if ydl_opts.get("writethumbnail"):
            args.append("--write-thumbnail")
        add_option("--convert-thumbnails", ydl_opts.get("convertthumbnails"))
        if ydl_opts.get("writeinfojson"):
            args.append("--write-info-json")

        if ydl_opts.get("writesubtitles"):
            args.append("--write-subs")
        if ydl_opts.get("writeautomaticsub"):
            args.append("--write-auto-subs")
        subtitles_langs = ydl_opts.get("subtitleslangs")
        if subtitles_langs:
            add_option("--sub-langs", ",".join(subtitles_langs))
        add_option("--sub-format", ydl_opts.get("subtitlesformat"))

        for processor in ydl_opts.get("postprocessors") or []:
            key = processor.get("key")
            if key == "FFmpegExtractAudio":
                args.append("--extract-audio")
                add_option("--audio-format", processor.get("preferredcodec"))
                add_option("--audio-quality", processor.get("preferredquality"))
            elif key == "FFmpegMetadata":
                args.append("--add-metadata")
            elif key == "EmbedThumbnail":
                args.append("--embed-thumbnail")
            elif key == "FFmpegSubtitlesConvertor":
                add_option("--convert-subs", processor.get("format"))

        args.append(url)
        return subprocess.list2cmdline(args)

    def _output_template(self, playlist: bool) -> str:
        if playlist:
            return str(
                self.options.output_dir
                / "%(playlist)s"
                / "%(playlist_index)03d - %(title).180B [%(id)s].%(ext)s"
            )
        return str(self.options.output_dir / "%(title).180B [%(id)s].%(ext)s")

    def _format_selector(self) -> str:
        if self.options.media_mode == MediaMode.AUDIO_MP3:
            return AUDIO_MP3_SELECTOR
        if self.options.media_mode == MediaMode.AUDIO_M4A:
            return AUDIO_M4A_SELECTOR
        if self.options.media_mode in {MediaMode.THUMBNAIL_ONLY, MediaMode.SUBTITLES_ONLY}:
            return "best"

        max_height = QUALITY_PRESETS.get(self.options.quality)
        if not max_height:
            return VIDEO_MP4_SELECTOR
        return _height_limited_video_selector(max_height)

    def _fallback_format_selector(self) -> str:
        if self.options.media_mode == MediaMode.VIDEO:
            return BEST_VIDEO_SELECTOR
        if self.options.media_mode == MediaMode.AUDIO_M4A:
            return AUDIO_MP3_SELECTOR
        if self.options.media_mode == MediaMode.AUDIO_MP3:
            return AUDIO_MP3_SELECTOR
        return "best"

    def _media_download_requires_js_runtime(self) -> bool:
        return self.options.media_mode in {
            MediaMode.VIDEO,
            MediaMode.AUDIO_MP3,
            MediaMode.AUDIO_M4A,
        }

    def _postprocessors(self) -> list[dict[str, Any]]:
        processors: list[dict[str, Any]] = []
        if self.options.media_mode in {MediaMode.AUDIO_MP3, MediaMode.AUDIO_M4A}:
            codec = "mp3" if self.options.media_mode == MediaMode.AUDIO_MP3 else "m4a"
            processors.append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": codec,
                    "preferredquality": self.options.audio_quality,
                }
            )
            processors.append({"key": "FFmpegMetadata"})
            if self.options.thumbnail and self.options.embed_thumbnail:
                processors.append({"key": "EmbedThumbnail"})

        if self.options.subtitles or self.options.media_mode == MediaMode.SUBTITLES_ONLY:
            processors.append(subtitle_postprocessor())

        return processors

    def _progress_hook(self, data: dict[str, Any]) -> None:
        if self.cancel_requested:
            raise DownloadCancelledError

        status = str(data.get("status", "working"))
        info = data.get("info_dict") or {}
        title = str(info.get("title") or "")
        filename = str(data.get("filename") or info.get("filepath") or "")

        if status == "finished" and filename:
            path = Path(filename)
            if path not in self._files_seen:
                self._files_seen.append(path)

        total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
        downloaded = data.get("downloaded_bytes") or 0
        percent = int(downloaded / total * 100) if total else (100 if status == "finished" else 0)

        event = ProgressEvent(
            job_id=self._active_job_id,
            status=status,
            percent=max(0, min(100, percent)),
            title=title,
            filename=filename,
            speed=format_bytes_per_second(data.get("speed")),
            eta=format_eta(data.get("eta")),
            playlist_index=info.get("playlist_index"),
            playlist_total=info.get("n_entries") or info.get("playlist_count"),
        )
        if self.progress_callback:
            self.progress_callback(event)

    def _log(self, message: str) -> None:
        if self.log_callback:
            self.log_callback(message)

    def _log_auth_strategy(self, auth_strategy: AuthStrategy, retry: bool = False) -> None:
        prefix = "Retrying with" if retry else "Using"
        if auth_strategy.is_cookie_file:
            self._log(f"{prefix} cookies.txt for YouTube authentication.")
        elif auth_strategy.is_browser:
            self._log(f"{prefix} browser cookies for YouTube authentication: {auth_strategy.display_name}.")
        else:
            if retry:
                self._log("Retrying without cookies. Public videos may still download.")
            else:
                self._log(
                    "Authentication unavailable: no cookies.txt and no supported browser cookies. "
                    "Public videos may still download."
                )

    def _auth_failure_log(self, auth_strategy: AuthStrategy) -> str:
        if auth_strategy.is_cookie_file:
            return "cookies.txt appears expired or invalid; trying fallback if available."
        if auth_strategy.is_browser:
            return "browser cookies appear expired, locked, or invalid."
        return "YouTube requested authentication, but no cookies are available."

    def _browser_cookie_failure_log(self, auth_strategy: AuthStrategy) -> str:
        if auth_strategy.is_browser:
            return f"Browser cookie extraction failed for {auth_strategy.display_name}; trying fallback if available."
        if auth_strategy.is_cookie_file:
            return "cookies.txt could not be used; trying browser cookie fallback if available."
        return "Browser cookie extraction failed."

    def _has_auth_retry(self, resolution: AuthResolution, index: int) -> bool:
        return any(strategy.attempted_auth for strategy in resolution.strategies[index + 1 :])

    def _has_browser_cookie_retry(self, resolution: AuthResolution, index: int) -> bool:
        return bool(resolution.strategies[index + 1 :])

    def _auth_was_attempted(self, resolution: AuthResolution) -> bool:
        return any(strategy.attempted_auth for strategy in resolution.strategies)

    def _clean_error_message(self, error_text: str) -> str:
        if is_youtube_challenge_component_error(error_text):
            return clean_youtube_challenge_component_error()
        if is_youtube_challenge_runtime_error(error_text):
            return clean_youtube_challenge_runtime_error()
        if is_live_event_ended_error(error_text):
            return clean_live_event_ended_error()
        if is_browser_cookie_extraction_error(error_text):
            return clean_browser_cookie_extraction_error()
        if is_authentication_error(error_text):
            return clean_authentication_error(True)
        cleaned = re.sub(r"https://github\.com/yt-dlp/yt-dlp/issues\S*", "", error_text)
        cleaned = re.sub(r"(?i)please report this issue.*", "", cleaned)
        return " ".join(cleaned.split()).strip() or "Download failed."
