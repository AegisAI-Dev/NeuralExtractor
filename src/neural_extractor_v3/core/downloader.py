"""yt-dlp powered download engine for Neural Extractor V3."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from neural_extractor_v3.config import (
    QUALITY_PRESETS,
    THROTTLE_SAFE_OPTIONS,
    YOUTUBE_REMOTE_COMPONENTS,
    YTDLP_ATTEMPT_TOTAL_TIMEOUT_SECONDS,
    YTDLP_INACTIVITY_TIMEOUT_SECONDS,
    YTDLP_STATUS_HEARTBEAT_SECONDS,
    YTDLP_TERMINATION_GRACE_SECONDS,
    app_data_dir,
    base_dir,
    bin_dir,
)
from neural_extractor_v3.core.auth import (
    AuthenticationState,
    AuthResolution,
    AuthStrategy,
    classify_browser_cookie_extraction_error,
    clean_browser_cookie_failure,
    resolve_auth_strategies,
)
from neural_extractor_v3.core.format_selection import (
    DiscoveredFormatSelection,
    select_discovered_format,
)
from neural_extractor_v3.core.js_runtime import (
    clean_youtube_challenge_runtime_error,
    ensure_youtube_js_runtime,
)
from neural_extractor_v3.core.pot_provider import get_po_token_provider
from neural_extractor_v3.core.process_control import (
    OwnedProcessSupervisor,
    ProcessCancelledError,
    ProcessInactivityTimeoutError,
    ProcessLaunchError,
    ProcessLimits,
    ProcessPhase,
    ProcessStatus,
    ProcessTotalTimeoutError,
    RecoveryState,
    is_process_running,
    recover_owned_process,
)
from neural_extractor_v3.core.subtitles import subtitle_postprocessor, subtitle_ydl_options
from neural_extractor_v3.core.youtube_connection import (
    ManagedBrowser,
    validate_managed_profile_path,
)
from neural_extractor_v3.core.youtube_errors import (
    FailureAnalysis,
    FailureCategory,
    classify_youtube_failure,
)
from neural_extractor_v3.core.ytdlp_worker import PROTOCOL_PREFIX
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
DEFAULT_YOUTUBE_CLIENTS = ("default",)
ALTERNATIVE_YOUTUBE_CLIENTS = (("web",),)
MAX_DOWNLOAD_ATTEMPTS = 6
MAX_FORMAT_DISCOVERY_ATTEMPTS = 2

HTTP_403_FINAL_MESSAGE = (
    "YouTube rejected media access with HTTP 403. Cookies were not used automatically; "
    "retry later or review the Activity Log for client, rate-limit, IP, or PO Token details."
)


class DownloadCancelledError(RuntimeError):
    """Raised after the exact owned process tree has been cancelled."""


@dataclass(slots=True)
class YtdlpCapturedOutput:
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)

    def stdout_text(self) -> str:
        return "\n".join(line for line in self.stdout if line).strip()

    def stderr_text(self) -> str:
        return "\n".join(line for line in self.stderr if line).strip()

    def diagnostic_text(self) -> str:
        return "\n".join(part for part in (self.stdout_text(), self.stderr_text()) if part)


@dataclass(frozen=True, slots=True)
class DownloadAttemptProfile:
    """One explicit, sanitized, bounded yt-dlp attempt profile."""

    auth_strategy: AuthStrategy
    format_selector: str
    player_clients: tuple[str, ...]
    node_runtime_available: bool
    remote_ejs_enabled: bool
    reason: str = "public_primary"

    def key(self) -> tuple[str, str, tuple[str, ...], str]:
        return (
            self.auth_strategy.provider_id,
            self.format_selector,
            self.player_clients,
            self.reason,
        )


@dataclass(frozen=True, slots=True)
class YtdlpRunResult:
    formats: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostic: str = ""


class YtdlpCaptureLogger:
    """Collect yt-dlp logger output for support diagnostics."""

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
    """Raised with complete, redacted yt-dlp attempt diagnostics."""

    def __init__(
        self,
        command: str,
        output: YtdlpCapturedOutput,
        exit_code: int | None = None,
        cause: BaseException | None = None,
        phase: str = "unknown",
        format_selector: str = "",
        player_clients: tuple[str, ...] = (),
        category_hint: FailureCategory | None = None,
    ) -> None:
        self.command = command
        self.output = output
        self.exit_code = exit_code
        self.cause = cause
        self.phase = phase
        self.format_selector = format_selector
        self.player_clients = player_clients
        self.category_hint = category_hint
        super().__init__(self.full_text())

    def diagnostic_text(self) -> str:
        details = self.output.diagnostic_text()
        if self.cause is not None:
            details = "\n".join(part for part in (details, str(self.cause)) if part)
        return details

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


def _height_limited_video_selector(height: int) -> str:
    return (
        f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
        f"b[height<={height}][ext=mp4]/"
        f"bv*[height<={height}]+ba/"
        f"b[height<={height}]/"
        "bv*+ba/b"
    )


def recover_stale_download_processes(log_callback: LogCallback | None = None) -> list[str]:
    """Recover only process trees carrying a valid Neural Extractor ownership record."""

    messages: list[str] = []
    state_dir = app_data_dir() / "process-state"
    records = state_dir.glob("active-*.json") if state_dir.exists() else ()
    for record in records:
        result = recover_owned_process(
            record,
            termination_grace=YTDLP_TERMINATION_GRACE_SECONDS,
            force_kill_wait=YTDLP_TERMINATION_GRACE_SECONDS,
        )
        if result.state == RecoveryState.TERMINATED:
            message = f"Recovered stale Neural Extractor download process tree (PID {result.pid})."
            messages.append(message)
            if log_callback:
                log_callback(message)
        elif result.state in {RecoveryState.INVALID_RECORD, RecoveryState.FAILED}:
            message = f"Stale download recovery: {result.state.value} ({result.detail or 'no detail'})."
            messages.append(message)
            if log_callback:
                log_callback(message)

    worker_temp_root = app_data_dir() / "worker-temp"
    if worker_temp_root.exists():
        for directory in worker_temp_root.glob("owner-*-*"):
            parts = directory.name.split("-", 2)
            try:
                owner_pid = int(parts[1])
            except (IndexError, ValueError):
                continue
            if owner_pid == os.getpid() or is_process_running(owner_pid):
                continue
            if _remove_owned_worker_temp(directory, worker_temp_root):
                message = f"Removed stale Neural Extractor worker temp state: {directory.name}."
                messages.append(message)
                if log_callback:
                    log_callback(message)
    return messages


def _remove_owned_worker_temp(directory: Path, worker_temp_root: Path) -> bool:
    try:
        resolved_root = worker_temp_root.resolve()
        resolved_directory = directory.resolve()
        if resolved_directory.parent != resolved_root or not directory.is_dir():
            return False
        shutil.rmtree(resolved_directory)
    except OSError:
        return False
    return True


class DownloadEngine:
    """Build yt-dlp options and execute isolated, state-driven download attempts."""

    def __init__(
        self,
        options: DownloadOptions,
        progress_callback: ProgressCallback | None = None,
        log_callback: LogCallback | None = None,
        *,
        process_limits: ProcessLimits | None = None,
        process_record_label: str = "download",
    ) -> None:
        self.options = options
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self._cancel_event = threading.Event()
        self._active_job_id = ""
        self._files_seen: list[Path] = []
        self._last_percent = 0
        self._last_activity_status = ""
        self._last_discovery_failure: FailureAnalysis | None = None
        self.js_runtime_status = ensure_youtube_js_runtime()
        self.po_token_provider_status = get_po_token_provider().status
        limits = process_limits or ProcessLimits(
            inactivity_timeout=YTDLP_INACTIVITY_TIMEOUT_SECONDS,
            total_timeout=YTDLP_ATTEMPT_TOTAL_TIMEOUT_SECONDS,
            status_interval=YTDLP_STATUS_HEARTBEAT_SECONDS,
            termination_grace=YTDLP_TERMINATION_GRACE_SECONDS,
            force_kill_wait=YTDLP_TERMINATION_GRACE_SECONDS,
        )
        safe_label = re.sub(r"[^a-z0-9_-]", "-", process_record_label.casefold()).strip("-")
        safe_label = safe_label or "download"
        record = (
            app_data_dir()
            / "process-state"
            / f"active-{safe_label}-{os.getpid()}-{uuid4().hex[:8]}.json"
        )
        self._supervisor = OwnedProcessSupervisor(
            limits,
            cancellation_event=self._cancel_event,
            ownership_record=record,
        )

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    def cancel(self) -> None:
        if self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self._log("Cancelling download")
        self._emit_activity_status("Cancelling download")
        self._supervisor.cancel()

    def download(self, job: DownloadJob) -> DownloadResult:
        self._active_job_id = job.job_id
        self._files_seen = []
        self._last_percent = 0
        self._last_activity_status = ""
        self._last_discovery_failure = None

        if self.cancel_requested:
            return self._failure_result(
                job,
                FailureCategory.DOWNLOAD_CANCELLED,
                "Download cancelled",
            )
        if not is_youtube_url(job.url):
            return self._failure_result(
                job,
                FailureCategory.UNKNOWN,
                f"Invalid YouTube URL: {job.url}",
            )

        url = self.prepare_url(job.url)
        self.options.output_dir.mkdir(parents=True, exist_ok=True)
        auth_resolution = resolve_auth_strategies(
            self.options.cookie_file,
            dedicated_browser=self.options.dedicated_browser,
            dedicated_browser_profile=self.options.dedicated_browser_profile,
            dedicated_firefox_profile=self.options.dedicated_firefox_profile,
            dedicated_application_data=app_data_dir(),
            allow_legacy_browser_fallback=self.options.legacy_browser_fallback,
        )
        auth_state = AuthenticationState(auth_resolution)

        self._log(self.js_runtime_status.diagnostic)
        self._log(self.po_token_provider_status.diagnostic)
        for message in auth_resolution.messages:
            self._log(message)

        if self._media_download_requires_js_runtime() and not self.js_runtime_status.found:
            message = clean_youtube_challenge_runtime_error()
            self._log(message)
            return self._failure_result(
                job,
                FailureCategory.JAVASCRIPT_RUNTIME_UNAVAILABLE,
                message,
            )

        public_strategy = self._public_strategy(auth_resolution)
        queue: deque[DownloadAttemptProfile] = deque(
            [self._profile(public_strategy, reason="public_primary")]
        )
        attempted_profiles: set[tuple[str, str, tuple[str, ...], str]] = set()
        clean_no_cookie_retry_used = False
        discovery_attempts = 0
        attempts = 0
        last_analysis = FailureAnalysis(
            FailureCategory.UNKNOWN,
            "Download failed before yt-dlp could start.",
        )

        while queue and attempts < MAX_DOWNLOAD_ATTEMPTS:
            if self.cancel_requested:
                return self._failure_result(
                    job,
                    FailureCategory.DOWNLOAD_CANCELLED,
                    "Download cancelled",
                )

            profile = queue.popleft()
            if profile.key() in attempted_profiles:
                continue
            attempted_profiles.add(profile.key())
            attempts += 1
            self._log_attempt_start(profile, attempts)

            try:
                self._run_profile(url, profile)
            except DownloadCancelledError:
                return self._failure_result(
                    job,
                    FailureCategory.DOWNLOAD_CANCELLED,
                    "Download cancelled",
                )
            except YtdlpRunError as error:
                self._log(error.full_text())
                analysis = self._analyse_error(error, profile)
                last_analysis = analysis
                self._log(
                    f"Attempt {attempts} classified as {analysis.category.value}: "
                    f"{analysis.user_message}"
                )

                if analysis.category in {
                    FailureCategory.NETWORK_INACTIVITY_TIMEOUT,
                    FailureCategory.TOTAL_ATTEMPT_TIMEOUT,
                    FailureCategory.NETWORK_TRANSIENT,
                }:
                    if not profile.auth_strategy.attempted_auth and not clean_no_cookie_retry_used:
                        clean_no_cookie_retry_used = True
                        self._log("No response received; recovering with a clean no-cookie subprocess.")
                        self._emit_activity_status("Starting clean retry")
                        queue.append(
                            self._profile(
                                public_strategy,
                                format_selector=profile.format_selector,
                                player_clients=profile.player_clients,
                                reason="public_clean_recovery",
                            )
                        )
                        continue
                    break

                if analysis.category == FailureCategory.AUTHENTICATION_REQUIRED:
                    next_strategy = self._next_authenticated_strategy(auth_state)
                    if next_strategy:
                        queue.append(self._profile(next_strategy, reason="authenticated_fallback"))
                        continue
                    break

                if analysis.category == FailureCategory.COOKIE_FILE_REJECTED:
                    auth_state.reject_cookie_file(analysis.user_message)
                    self._log("cookies.txt may be stale or rejected; it will not be repeated in this job.")
                    next_strategy = self._next_authenticated_strategy(auth_state)
                    if next_strategy:
                        queue.append(self._profile(next_strategy, reason="authenticated_fallback"))
                        continue
                    break

                if analysis.category in {
                    FailureCategory.BROWSER_COOKIE_DATABASE_LOCKED,
                    FailureCategory.BROWSER_COOKIE_DECRYPTION_FAILED,
                    FailureCategory.BROWSER_COOKIE_EXTRACTION_FAILED,
                }:
                    browser = profile.auth_strategy.browser or profile.auth_strategy.display_name.lower()
                    failure_kind = classify_browser_cookie_extraction_error(error.diagnostic_text())
                    auth_state.disable_browser(browser, analysis.category.value)
                    self._log(
                        clean_browser_cookie_failure(
                            failure_kind,
                            profile.auth_strategy.display_name,
                        )
                    )
                    next_strategy = self._next_authenticated_strategy(auth_state)
                    if next_strategy:
                        queue.append(self._profile(next_strategy, reason="authenticated_fallback"))
                        continue
                    break

                if analysis.category == FailureCategory.HTTP_403_MEDIA_REJECTED:
                    if profile.auth_strategy.attempted_auth and auth_state.authenticated_fallback_justified:
                        next_strategy = self._next_authenticated_strategy(auth_state)
                        if next_strategy:
                            queue.append(self._profile(next_strategy, reason="authenticated_fallback"))
                            continue
                        break
                    if not clean_no_cookie_retry_used:
                        clean_no_cookie_retry_used = True
                        self._log("HTTP 403 is not proof of authentication. Starting one clean no-cookie retry.")
                        self._emit_activity_status("Starting clean retry")
                        queue.append(
                            self._profile(
                                public_strategy,
                                format_selector=profile.format_selector,
                                player_clients=profile.player_clients,
                                reason="public_clean_recovery",
                            )
                        )
                        continue
                    if discovery_attempts < MAX_FORMAT_DISCOVERY_ATTEMPTS:
                        discovery_attempts += 1
                        alternative = self._discover_profile(
                            url,
                            public_strategy,
                            ALTERNATIVE_YOUTUBE_CLIENTS[0],
                            reason="public_alternative_client",
                        )
                        if alternative:
                            queue.append(alternative)
                            continue
                        if self._queue_authentication_from_discovery(auth_state, queue):
                            continue
                        if self._last_discovery_failure and self._last_discovery_failure.category in {
                            FailureCategory.PO_TOKEN_REQUIRED,
                            FailureCategory.ONLY_IMAGE_FORMATS_AVAILABLE,
                            FailureCategory.JAVASCRIPT_RUNTIME_UNAVAILABLE,
                            FailureCategory.CHALLENGE_SOLVER_COMPONENT_UNAVAILABLE,
                        }:
                            last_analysis = self._last_discovery_failure
                        else:
                            last_analysis = FailureAnalysis(
                                FailureCategory.HTTP_403_MEDIA_REJECTED,
                                HTTP_403_FINAL_MESSAGE,
                            )
                    else:
                        last_analysis = FailureAnalysis(
                            FailureCategory.HTTP_403_MEDIA_REJECTED,
                            HTTP_403_FINAL_MESSAGE,
                        )
                    break

                if analysis.category == FailureCategory.REQUESTED_FORMAT_UNAVAILABLE:
                    if discovery_attempts < MAX_FORMAT_DISCOVERY_ATTEMPTS:
                        discovery_attempts += 1
                        discovered = self._discover_profile(
                            url,
                            profile.auth_strategy,
                            profile.player_clients,
                            reason="discovered_available_format",
                        )
                        if discovered:
                            queue.append(discovered)
                            continue
                        if self._queue_authentication_from_discovery(auth_state, queue):
                            continue
                        if self._last_discovery_failure:
                            last_analysis = self._last_discovery_failure
                    break

                if analysis.category == FailureCategory.ONLY_IMAGE_FORMATS_AVAILABLE:
                    if (
                        not profile.auth_strategy.attempted_auth
                        and discovery_attempts < MAX_FORMAT_DISCOVERY_ATTEMPTS
                    ):
                        discovery_attempts += 1
                        alternative = self._discover_profile(
                            url,
                            public_strategy,
                            ALTERNATIVE_YOUTUBE_CLIENTS[0],
                            reason="public_image_only_recovery",
                        )
                        if alternative:
                            queue.append(alternative)
                            continue
                        if self._queue_authentication_from_discovery(auth_state, queue):
                            continue
                        if self._last_discovery_failure:
                            last_analysis = self._last_discovery_failure
                    break

                break
            else:
                message = "Download completed"
                if self._files_seen:
                    message = f"Download completed: {self._files_seen[-1].name}"
                return DownloadResult(job.job_id, True, message, self._files_seen)

        self._log(
            f"Retry plan exhausted after {attempts} download attempt(s) and "
            f"{discovery_attempts} format discovery attempt(s)."
        )
        return self._failure_result(job, last_analysis.category, last_analysis.user_message)

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
        opts: dict[str, Any] = {
            "outtmpl": self._output_template(playlist),
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
            "extractor_args": {"youtube": {"player_client": list(DEFAULT_YOUTUBE_CLIENTS)}},
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
        postprocessors = self._postprocessors()
        if postprocessors:
            opts["postprocessors"] = postprocessors
        return opts

    def run_authentication_preflight(
        self,
        url: str,
        profile_path: Path,
        browser: ManagedBrowser | str = ManagedBrowser.FIREFOX,
    ) -> YtdlpRunResult:
        """Run one bounded metadata-only request with an exact managed profile."""
        selected_browser = ManagedBrowser(browser)
        profile = validate_managed_profile_path(
            profile_path,
            browser=selected_browser,
            application_data=app_data_dir(),
        )
        extraction_profile = (
            profile / "Default" if selected_browser is ManagedBrowser.CHROME else profile
        )
        strategy = AuthStrategy(
            kind="dedicated_browser",
            display_name=f"Dedicated Neural Extractor {selected_browser.display_name} profile",
            attempted_auth=True,
            ydl_options={
                "cookiesfrombrowser": (selected_browser.value, str(extraction_profile))
            },
        )
        prepared_url = self.prepare_url(url)
        attempt = self._profile(strategy, reason="youtube_connection_verification")
        options = self._options_for_attempt_profile(prepared_url, attempt)
        return self._run_yt_dlp(prepared_url, options, discover_only=True)

    def _public_strategy(self, resolution: AuthResolution) -> AuthStrategy:
        strategy = next((item for item in resolution.strategies if not item.attempted_auth), None)
        if strategy is None:
            return AuthStrategy("none", "no authentication", {}, attempted_auth=False)
        return strategy

    def _profile(
        self,
        auth_strategy: AuthStrategy,
        *,
        format_selector: str | None = None,
        player_clients: tuple[str, ...] = DEFAULT_YOUTUBE_CLIENTS,
        reason: str,
    ) -> DownloadAttemptProfile:
        return DownloadAttemptProfile(
            auth_strategy=auth_strategy,
            format_selector=format_selector or self._format_selector(),
            player_clients=player_clients,
            node_runtime_available=self.js_runtime_status.found,
            remote_ejs_enabled="ejs:github" in YOUTUBE_REMOTE_COMPONENTS,
            reason=reason,
        )

    def _run_profile(self, prepared_url: str, profile: DownloadAttemptProfile) -> YtdlpRunResult:
        ydl_opts = self._options_for_attempt_profile(prepared_url, profile)
        self._log(f"selected format selector: {profile.format_selector}")
        self._log(f"Download attempt profile: {self._attempt_profile_summary(profile)}")
        return self._run_yt_dlp(prepared_url, ydl_opts)

    def _options_for_attempt_profile(
        self,
        prepared_url: str,
        profile: DownloadAttemptProfile,
    ) -> dict[str, Any]:
        if profile.auth_strategy.is_dedicated_browser:
            configured = profile.auth_strategy.ydl_options.get("cookiesfrombrowser") or ()
            configured_browser = configured[0] if configured else ""
            configured_profile = configured[1] if len(configured) > 1 else ""
            try:
                selected_browser = ManagedBrowser(str(configured_browser))
                managed_root = Path(str(configured_profile))
                if selected_browser is ManagedBrowser.CHROME:
                    if managed_root.name.casefold() != "default":
                        raise ValueError("Chrome extraction must use the managed Default profile.")
                    managed_root = managed_root.parent
                validate_managed_profile_path(
                    managed_root,
                    browser=selected_browser,
                    application_data=app_data_dir(),
                )
            except (IndexError, TypeError, ValueError, OSError):
                output = YtdlpCapturedOutput(
                    stderr=["Dedicated browser profile failed safety validation."]
                )
                raise YtdlpRunError(
                    "yt-dlp <dedicated-profile-validation>",
                    output,
                    exit_code=1,
                    phase="startup",
                    category_hint=FailureCategory.DEDICATED_PROFILE_INVALID,
                )
        ydl_opts = self.build_ydl_options(prepared_url, profile.auth_strategy)
        ydl_opts["format"] = profile.format_selector
        extractor_args = dict(ydl_opts.get("extractor_args") or {})
        youtube_args = dict(extractor_args.get("youtube") or {})
        youtube_args["player_client"] = list(profile.player_clients)
        extractor_args["youtube"] = youtube_args
        ydl_opts["extractor_args"] = extractor_args
        return ydl_opts

    def _discover_profile(
        self,
        prepared_url: str,
        auth_strategy: AuthStrategy,
        player_clients: tuple[str, ...],
        *,
        reason: str,
    ) -> DownloadAttemptProfile | None:
        if self.cancel_requested:
            raise DownloadCancelledError
        self._last_discovery_failure = None
        self._log(
            "Bounded format discovery: "
            f"auth={auth_strategy.provider_id}; client={','.join(player_clients)}"
        )
        probe_profile = self._profile(
            auth_strategy,
            player_clients=player_clients,
            reason=f"{reason}_discovery",
        )
        probe_opts = self._options_for_attempt_profile(prepared_url, probe_profile)
        try:
            result = self._run_yt_dlp(prepared_url, probe_opts, discover_only=True)
        except DownloadCancelledError:
            raise
        except YtdlpRunError as error:
            self._log(error.full_text())
            analysis = self._analyse_error(error, probe_profile)
            self._last_discovery_failure = analysis
            self._log(
                f"Format discovery failed as {analysis.category.value}: {analysis.user_message}"
            )
            return None

        selection = select_discovered_format(
            result.formats,
            self.options.media_mode,
            max_height=QUALITY_PRESETS.get(self.options.quality),
        )
        self._log_discovery_selection(selection)
        if selection.image_only:
            self._log("Only image formats available; no media download will be attempted.")
            self._last_discovery_failure = FailureAnalysis(
                FailureCategory.ONLY_IMAGE_FORMATS_AVAILABLE,
                "YouTube exposed only image formats; no downloadable audio or video format was available.",
            )
            return None
        if not selection.selector:
            self._last_discovery_failure = FailureAnalysis(
                FailureCategory.REQUESTED_FORMAT_UNAVAILABLE,
                "Format discovery found no usable audio or video format IDs.",
            )
            return None
        return self._profile(
            auth_strategy,
            format_selector=selection.selector,
            player_clients=player_clients,
            reason=reason,
        )

    def _run_yt_dlp(
        self,
        prepared_url: str,
        ydl_opts: dict[str, Any],
        *,
        discover_only: bool = False,
    ) -> YtdlpRunResult:
        playlist = should_download_playlist(prepared_url, self.options.playlist_mode.value)
        command = self._yt_dlp_command(prepared_url, ydl_opts)
        self._log(f"yt-dlp command:\n{command}")

        request_opts = self._json_safe_options(ydl_opts)
        request = {
            "url": prepared_url,
            "options": request_opts,
            "playlist": playlist,
            "mode": "discover" if discover_only else "download",
            "activity_label": self._download_activity_label(),
        }
        output = YtdlpCapturedOutput()
        formats: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}
        phase = "discovery" if discover_only else "preflight"
        worker_error = ""
        protocol_error = ""
        buffers = {"stdout": "", "stderr": ""}
        parser_lock = threading.Lock()

        def handle_event_line(line: str, fallback_stream: str) -> None:
            nonlocal phase, worker_error, protocol_error, formats, metadata
            if not line:
                return
            if not line.startswith(PROTOCOL_PREFIX):
                cleaned = self._redact_diagnostic_text(line)
                target = output.stderr if fallback_stream == "stderr" else output.stdout
                target.append(cleaned)
                return
            try:
                event = json.loads(line[len(PROTOCOL_PREFIX) :])
            except json.JSONDecodeError:
                protocol_error = "The internal yt-dlp worker emitted a malformed JSON frame."
                output.stderr.append(protocol_error)
                output.stderr.append(self._redact_diagnostic_text(line))
                return
            if not isinstance(event, dict):
                protocol_error = "The internal yt-dlp worker emitted a non-object JSON frame."
                output.stderr.append(protocol_error)
                return
            kind = event.get("kind")
            if kind == "log":
                message = self._redact_diagnostic_text(str(event.get("message") or ""))
                stream = str(event.get("stream") or fallback_stream)
                (output.stderr if stream == "stderr" else output.stdout).append(message)
                lowered = message.lower()
                if "retry" in lowered and any(
                    token in lowered for token in ("network", "fragment", "http error", "unable")
                ):
                    self._emit_activity_status("Waiting for YouTube retry")
            elif kind == "phase":
                phase = str(event.get("phase") or phase)
                message = str(event.get("message") or "")
                if message:
                    self._emit_activity_status(message)
            elif kind == "progress":
                data = event.get("data")
                if isinstance(data, dict):
                    self._progress_hook(data)
            elif kind == "metadata":
                payload = event.get("formats")
                if isinstance(payload, list):
                    formats = [item for item in payload if isinstance(item, dict)]
                metadata = {
                    key: event.get(key)
                    for key in ("id", "title", "availability", "live_status")
                    if event.get(key) is not None
                }
            elif kind == "error":
                phase = str(event.get("phase") or phase)
                worker_error = self._redact_diagnostic_text(str(event.get("message") or ""))
                if worker_error:
                    output.stderr.append(worker_error)
                worker_traceback = self._redact_diagnostic_text(str(event.get("traceback") or ""))
                if worker_traceback:
                    output.stderr.append(worker_traceback)

        def feed(stream: str, chunk: str) -> None:
            with parser_lock:
                buffers[stream] += chunk
                while "\n" in buffers[stream]:
                    line, buffers[stream] = buffers[stream].split("\n", 1)
                    handle_event_line(line.rstrip("\r"), stream)

        def flush_buffers() -> None:
            with parser_lock:
                for stream, remaining in tuple(buffers.items()):
                    if remaining:
                        handle_event_line(remaining.rstrip("\r"), stream)
                        buffers[stream] = ""

        attempt_temp = self._create_attempt_temp()
        try:
            try:
                result = self._supervisor.run(
                    self._worker_command(),
                    stdin_data=json.dumps(request, ensure_ascii=False),
                    cwd=base_dir(),
                    env=self._worker_environment(attempt_temp),
                    stdout_callback=lambda chunk: feed("stdout", chunk),
                    stderr_callback=lambda chunk: feed("stderr", chunk),
                    status_callback=self._on_process_status,
                    cancel_requested=self._cancel_event.is_set,
                )
            finally:
                self._cleanup_attempt_temp(attempt_temp)
        except ProcessCancelledError as exc:
            flush_buffers()
            self._append_uncaptured_process_output(output, exc.result.stdout, exc.result.stderr)
            raise DownloadCancelledError from exc
        except ProcessInactivityTimeoutError as exc:
            flush_buffers()
            self._append_uncaptured_process_output(output, exc.result.stdout, exc.result.stderr)
            output.stderr.append(
                f"Network inactivity timeout after {exc.result.elapsed_seconds:.1f} seconds; "
                f"owned process tree terminated; forced={exc.result.forced_kill}."
            )
            raise YtdlpRunError(
                command,
                output,
                exit_code=exc.result.returncode,
                cause=exc,
                phase=phase,
                format_selector=str(ydl_opts.get("format") or ""),
                player_clients=self._player_clients_from_options(ydl_opts),
                category_hint=FailureCategory.NETWORK_INACTIVITY_TIMEOUT,
            ) from exc
        except ProcessTotalTimeoutError as exc:
            flush_buffers()
            self._append_uncaptured_process_output(output, exc.result.stdout, exc.result.stderr)
            output.stderr.append(
                f"Total attempt timeout after {exc.result.elapsed_seconds:.1f} seconds; "
                f"owned process tree terminated; forced={exc.result.forced_kill}."
            )
            raise YtdlpRunError(
                command,
                output,
                exit_code=exc.result.returncode,
                cause=exc,
                phase=phase,
                format_selector=str(ydl_opts.get("format") or ""),
                player_clients=self._player_clients_from_options(ydl_opts),
                category_hint=FailureCategory.TOTAL_ATTEMPT_TIMEOUT,
            ) from exc
        except ProcessLaunchError as exc:
            flush_buffers()
            output.stderr.append(self._redact_diagnostic_text(str(exc)))
            raise YtdlpRunError(
                command,
                output,
                exit_code=1,
                cause=exc,
                phase="startup",
                format_selector=str(ydl_opts.get("format") or ""),
                player_clients=self._player_clients_from_options(ydl_opts),
            ) from exc

        flush_buffers()
        if result.returncode or worker_error or protocol_error:
            raise YtdlpRunError(
                command,
                output,
                exit_code=result.returncode,
                phase=phase,
                format_selector=str(ydl_opts.get("format") or ""),
                player_clients=self._player_clients_from_options(ydl_opts),
                category_hint=(
                    FailureCategory.WORKER_PROTOCOL_ERROR if protocol_error else None
                ),
            )
        return YtdlpRunResult(
            formats=formats,
            metadata=metadata,
            diagnostic=output.diagnostic_text(),
        )

    def _queue_authentication_from_discovery(
        self,
        auth_state: AuthenticationState,
        queue: deque[DownloadAttemptProfile],
    ) -> bool:
        failure = self._last_discovery_failure
        if not failure or failure.category != FailureCategory.AUTHENTICATION_REQUIRED:
            return False
        next_strategy = self._next_authenticated_strategy(auth_state)
        if not next_strategy:
            return False
        queue.append(self._profile(next_strategy, reason="authenticated_fallback"))
        return True

    def _next_authenticated_strategy(
        self,
        auth_state: AuthenticationState,
    ) -> AuthStrategy | None:
        auth_state.justify_authenticated_fallback()
        if self.options.guided_youtube_auth and not (
            self.options.dedicated_browser_profile or self.options.dedicated_firefox_profile
        ):
            return None
        return auth_state.next_authenticated_strategy()

    def _analyse_error(
        self,
        error: YtdlpRunError,
        profile: DownloadAttemptProfile,
    ) -> FailureAnalysis:
        if error.category_hint == FailureCategory.NETWORK_INACTIVITY_TIMEOUT:
            return FailureAnalysis(
                FailureCategory.NETWORK_INACTIVITY_TIMEOUT,
                "No yt-dlp output was received within the inactivity limit. The attempt was stopped safely.",
                transient=True,
            )
        if error.category_hint == FailureCategory.TOTAL_ATTEMPT_TIMEOUT:
            return FailureAnalysis(
                FailureCategory.TOTAL_ATTEMPT_TIMEOUT,
                "The yt-dlp attempt reached the maximum total duration and was stopped safely.",
                transient=True,
            )
        if error.category_hint == FailureCategory.DEDICATED_PROFILE_INVALID:
            return FailureAnalysis(
                FailureCategory.DEDICATED_PROFILE_INVALID,
                "The dedicated browser profile is invalid or unavailable.",
                authentication_specific=True,
            )
        if error.category_hint == FailureCategory.WORKER_PROTOCOL_ERROR:
            return FailureAnalysis(
                FailureCategory.WORKER_PROTOCOL_ERROR,
                "The internal yt-dlp worker returned malformed protocol data. Retry the download; "
                "if it repeats, include the Activity Log in a support report.",
            )
        return classify_youtube_failure(
            error.diagnostic_text(),
            auth_kind=profile.auth_strategy.kind,
            javascript_runtime_available=self.js_runtime_status.found,
        )

    def _worker_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--internal-ytdlp-worker"]
        return [sys.executable, "-m", "neural_extractor_v3.core.ytdlp_worker"]

    def _worker_environment(self, attempt_temp: Path | None = None) -> dict[str, str]:
        environment = os.environ.copy()
        source_dir = base_dir() / "src"
        existing = environment.get("PYTHONPATH", "")
        paths = [str(source_dir)]
        if existing:
            paths.append(existing)
        environment["PYTHONPATH"] = os.pathsep.join(paths)
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        if attempt_temp is not None:
            environment["TEMP"] = str(attempt_temp)
            environment["TMP"] = str(attempt_temp)
        return environment

    def _create_attempt_temp(self) -> Path:
        root = app_data_dir() / "worker-temp"
        directory = root / f"owner-{os.getpid()}-{uuid4().hex}"
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def _cleanup_attempt_temp(self, directory: Path) -> None:
        with contextlib.suppress(OSError):
            _remove_owned_worker_temp(directory, app_data_dir() / "worker-temp")

    def _json_safe_options(self, ydl_opts: dict[str, Any]) -> dict[str, Any]:
        safe = dict(ydl_opts)
        safe.pop("logger", None)
        safe.pop("progress_hooks", None)
        return json.loads(json.dumps(safe, default=str))

    def _on_process_status(self, status: ProcessStatus) -> None:
        if status.phase == ProcessPhase.ACTIVE:
            self._emit_activity_status(
                f"Active download ({status.elapsed_seconds / 60:.0f}m elapsed; "
                f"last output {status.inactive_seconds:.0f}s ago)"
            )
        elif status.phase == ProcessPhase.INACTIVITY_TIMEOUT:
            self._emit_activity_status("No response received; recovering")
            self._log("No response received; recovering")
        elif status.phase == ProcessPhase.TOTAL_TIMEOUT:
            self._emit_activity_status("Maximum attempt duration reached; recovering")
            self._log("Maximum attempt duration reached; recovering")
        elif status.phase == ProcessPhase.CANCELLING:
            self._emit_activity_status("Cancelling download")

    def _append_uncaptured_process_output(
        self,
        output: YtdlpCapturedOutput,
        stdout: str,
        stderr: str,
    ) -> None:
        # Reader callbacks normally captured every line. Only add raw non-protocol
        # text here when the callbacks could not parse anything at all.
        if stdout and not output.stdout and PROTOCOL_PREFIX not in stdout:
            output.stdout.extend(self._redact_diagnostic_text(stdout).splitlines())
        if stderr and not output.stderr and PROTOCOL_PREFIX not in stderr:
            output.stderr.extend(self._redact_diagnostic_text(stderr).splitlines())

    def _player_clients_from_options(self, ydl_opts: dict[str, Any]) -> tuple[str, ...]:
        extractor_args = ydl_opts.get("extractor_args") or {}
        youtube_args = extractor_args.get("youtube") or {}
        player_clients = youtube_args.get("player_client") or ()
        if isinstance(player_clients, str):
            return tuple(item.strip() for item in player_clients.split(",") if item.strip())
        return tuple(str(item) for item in player_clients if item)

    def _log_attempt_start(self, profile: DownloadAttemptProfile, attempt: int) -> None:
        if profile.reason == "public_primary":
            self._log("Starting public YouTube attempt without cookies (auth=none).")
            self._emit_activity_status("Preparing YouTube metadata")
        elif profile.reason == "public_clean_recovery":
            self._log("Starting clean retry without cookies (auth=none).")
            self._emit_activity_status("Starting clean retry")
        elif profile.auth_strategy.is_cookie_file:
            self._log("Authenticating with cookies.txt.")
            self._emit_activity_status("Authenticating with cookies.txt")
        elif profile.auth_strategy.is_dedicated_browser:
            self._log(
                f"Using the {profile.auth_strategy.display_name} for YouTube authentication."
            )
            self._emit_activity_status("Authenticating with the YouTube connection")
        elif profile.auth_strategy.is_browser:
            self._log(f"Trying browser cookies from {profile.auth_strategy.display_name}.")
            self._emit_activity_status(
                f"Trying browser cookies from {profile.auth_strategy.display_name}"
            )
        else:
            self._log("Trying an alternative no-cookie YouTube client with discovered formats.")
        self._log(f"Download attempt {attempt}/{MAX_DOWNLOAD_ATTEMPTS}")

    def _attempt_profile_summary(self, profile: DownloadAttemptProfile) -> str:
        if profile.auth_strategy.is_cookie_file:
            auth_source = "cookies.txt"
        elif profile.auth_strategy.is_dedicated_browser:
            auth_source = f"dedicated-{profile.auth_strategy.browser or 'browser'}"
        elif profile.auth_strategy.is_browser:
            auth_source = f"browser:{profile.auth_strategy.display_name}"
        else:
            auth_source = "none"
        node_state = "found" if profile.node_runtime_available else "not found"
        ejs_state = "enabled" if profile.remote_ejs_enabled else "disabled"
        return (
            f"auth={auth_source}; format={profile.format_selector}; "
            f"client={','.join(profile.player_clients) or 'default'}; "
            f"node={node_state}; remote EJS={ejs_state}; reason={profile.reason}"
        )

    def _log_discovery_selection(self, selection: DiscoveredFormatSelection) -> None:
        if selection.selector:
            self._log(
                f"Format discovery found {selection.media_format_count} media format(s); "
                f"selected actual format ID(s): {selection.selector}."
            )
        elif selection.image_only:
            self._log("Format discovery returned only image formats.")
        else:
            self._log("Format discovery returned no usable media format IDs.")

    def _yt_dlp_command(self, url: str, ydl_opts: dict[str, Any]) -> str:
        args = ["yt-dlp"]

        def add_option(flag: str, value: Any) -> None:
            if value is not None:
                args.extend([flag, str(value)])

        add_option("-f", ydl_opts.get("format"))
        add_option("-o", ydl_opts.get("outtmpl"))
        add_option("--merge-output-format", ydl_opts.get("merge_output_format"))
        args.append("--no-playlist" if ydl_opts.get("noplaylist") else "--yes-playlist")
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

        player_clients = self._player_clients_from_options(ydl_opts)
        if player_clients:
            add_option("--extractor-args", f"youtube:player_client={','.join(player_clients)}")
        if ydl_opts.get("ffmpeg_location"):
            add_option("--ffmpeg-location", ydl_opts["ffmpeg_location"])
        if ydl_opts.get("cookiefile"):
            add_option("--cookies", "<cookies.txt>")
        if ydl_opts.get("cookiesfrombrowser"):
            browser_spec = ydl_opts["cookiesfrombrowser"]
            value = str(browser_spec[0])
            if len(browser_spec) > 1 and browser_spec[1]:
                value += ":<dedicated-profile>"
            add_option("--cookies-from-browser", value)
        if ydl_opts.get("js_runtimes"):
            runtime_args = []
            for name, config in ydl_opts["js_runtimes"].items():
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

    def _download_activity_label(self) -> str:
        return {
            MediaMode.VIDEO: "Downloading video",
            MediaMode.AUDIO_MP3: "Downloading audio",
            MediaMode.AUDIO_M4A: "Downloading audio",
            MediaMode.SUBTITLES_ONLY: "Downloading subtitles",
            MediaMode.THUMBNAIL_ONLY: "Downloading thumbnail",
        }[self.options.media_mode]

    def _progress_hook(self, data: dict[str, Any]) -> None:
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
        self._last_percent = max(0, min(100, percent))
        event = ProgressEvent(
            job_id=self._active_job_id,
            status=status,
            percent=self._last_percent,
            title=title,
            filename=filename,
            speed=format_bytes_per_second(data.get("speed")),
            eta=format_eta(data.get("eta")),
            playlist_index=info.get("playlist_index"),
            playlist_total=info.get("n_entries") or info.get("playlist_count"),
        )
        if self.progress_callback:
            self.progress_callback(event)

    def _emit_activity_status(self, status: str) -> None:
        if not status or status == self._last_activity_status:
            return
        self._last_activity_status = status
        if self.progress_callback:
            self.progress_callback(
                ProgressEvent(
                    job_id=self._active_job_id,
                    status=status,
                    percent=self._last_percent,
                )
            )

    def _failure_result(
        self,
        job: DownloadJob,
        category: FailureCategory,
        message: str,
    ) -> DownloadResult:
        return DownloadResult(
            job.job_id,
            False,
            message,
            self._files_seen,
            category.value,
        )

    def _redact_diagnostic_text(self, value: str) -> str:
        text = str(value or "")
        if self.options.cookie_file:
            text = text.replace(str(self.options.cookie_file), "<cookies.txt>")
        if self.options.dedicated_firefox_profile:
            text = text.replace(
                str(self.options.dedicated_firefox_profile),
                "<dedicated-firefox-profile>",
            )
        if self.options.dedicated_browser_profile:
            text = text.replace(
                str(self.options.dedicated_browser_profile),
                "<dedicated-browser-profile>",
            )
        home = str(Path.home())
        if home:
            text = text.replace(home, "<user-profile>")
        text = re.sub(
            r"(?i)\b(cookie|authorization)\s*[:=]\s*\S+",
            r"\1=<redacted>",
            text,
        )
        return text

    def _clean_error_message(self, error_text: str) -> str:
        analysis = classify_youtube_failure(
            error_text,
            javascript_runtime_available=self.js_runtime_status.found,
        )
        if analysis.category != FailureCategory.UNKNOWN:
            return analysis.user_message
        cleaned = re.sub(r"https://github\.com/yt-dlp/yt-dlp/issues\S*", "", error_text)
        cleaned = re.sub(r"(?i)please report this issue.*", "", cleaned)
        return " ".join(cleaned.split()).strip() or analysis.user_message

    def _log(self, message: str) -> None:
        if self.log_callback:
            self.log_callback(message)


__all__ = [
    "AUDIO_M4A_SELECTOR",
    "AUDIO_MP3_SELECTOR",
    "DEFAULT_YOUTUBE_CLIENTS",
    "DownloadAttemptProfile",
    "DownloadCancelledError",
    "DownloadEngine",
    "HTTP_403_FINAL_MESSAGE",
    "MAX_DOWNLOAD_ATTEMPTS",
    "VIDEO_MP4_SELECTOR",
    "YtdlpCaptureLogger",
    "YtdlpCapturedOutput",
    "YtdlpRunError",
    "YtdlpRunResult",
    "recover_stale_download_processes",
]
