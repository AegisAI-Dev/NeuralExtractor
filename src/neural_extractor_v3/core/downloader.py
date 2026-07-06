"""yt-dlp powered download engine for Neural Extractor V3."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yt_dlp

from neural_extractor_v3.config import QUALITY_PRESETS, THROTTLE_SAFE_OPTIONS, bin_dir
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
    is_youtube_url,
    normalize_single_video_url,
    normalize_user_url,
    should_download_playlist,
)

ProgressCallback = Callable[[ProgressEvent], None]
LogCallback = Callable[[str], None]


class DownloadCancelledError(RuntimeError):
    """Raised when a download is cancelled by the user."""


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

        for message in auth_resolution.messages:
            self._log(message)

        last_auth_error = ""
        browser_cookie_error = ""
        for index, auth_strategy in enumerate(auth_resolution.strategies):
            try:
                self._log(f"Starting {self.options.media_mode.label}: {url}")
                self._log_auth_strategy(auth_strategy, retry=index > 0)
                self._download_with_strategy(url, job.url, auth_strategy)
                break
            except DownloadCancelledError:
                return DownloadResult(job.job_id, False, "Download cancelled by user", self._files_seen)
            except Exception as exc:
                error_text = str(exc)
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
                    if self._has_browser_cookie_retry(auth_resolution, index):
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
                    if self._has_auth_retry(auth_resolution, index):
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
                    f"Download failed: {self._clean_error_message(error_text)}",
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
        if self.options.playlist_mode == PlaylistMode.SINGLE:
            return normalize_single_video_url(url)
        return normalize_user_url(url)

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
            "merge_output_format": "mp4",
            "ignoreerrors": playlist,
            "noplaylist": not playlist,
            "no_warnings": True,
            "quiet": True,
            "windowsfilenames": True,
            "restrictfilenames": self.options.restrict_filenames,
            "overwrites": self.options.overwrite,
            "continuedl": True,
            "progress_hooks": [self._progress_hook],
            "extractor_args": {"youtube": {"player_client": ["mweb", "default"]}},
            **THROTTLE_SAFE_OPTIONS,
        }

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
        original_url: str,
        auth_strategy: AuthStrategy,
    ) -> None:
        ydl_opts = self.build_ydl_options(original_url, auth_strategy=auth_strategy)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Explicit preflight uses the same YoutubeDL instance and auth options as final download.
            ydl.extract_info(prepared_url, download=False)
            retcode = ydl.download([prepared_url])
            if retcode:
                raise RuntimeError(f"yt-dlp returned exit code {retcode}")

    def _output_template(self, playlist: bool) -> str:
        if playlist:
            return str(
                self.options.output_dir
                / "%(playlist)s"
                / "%(playlist_index)03d - %(title).180B [%(id)s].%(ext)s"
            )
        return str(self.options.output_dir / "%(title).180B [%(id)s].%(ext)s")

    def _format_selector(self) -> str:
        if self.options.media_mode in {MediaMode.AUDIO_MP3, MediaMode.AUDIO_M4A}:
            return "bestaudio/best"
        if self.options.media_mode in {MediaMode.THUMBNAIL_ONLY, MediaMode.SUBTITLES_ONLY}:
            return "best"

        max_height = QUALITY_PRESETS.get(self.options.quality)
        if not max_height:
            return "bestvideo*+bestaudio/best"
        return f"bestvideo*[height<={max_height}]+bestaudio/best[height<={max_height}]/best"

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
        return any(strategy.is_browser for strategy in resolution.strategies[index + 1 :])

    def _auth_was_attempted(self, resolution: AuthResolution) -> bool:
        return any(strategy.attempted_auth for strategy in resolution.strategies)

    def _clean_error_message(self, error_text: str) -> str:
        if is_live_event_ended_error(error_text):
            return clean_live_event_ended_error()
        if is_browser_cookie_extraction_error(error_text):
            return clean_browser_cookie_extraction_error()
        if is_authentication_error(error_text):
            return clean_authentication_error(True)
        cleaned = re.sub(r"https://github\.com/yt-dlp/yt-dlp/issues\S*", "", error_text)
        cleaned = re.sub(r"(?i)please report this issue.*", "", cleaned)
        return " ".join(cleaned.split()).strip() or "Download failed."
