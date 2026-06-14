"""Video download functionality using yt-dlp."""

import os
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yt_dlp

from neural_extractor.config import BIN_DIR, MAX_PLAYLIST_VIDEOS
from neural_extractor.logger import logger
from neural_extractor.subtitles import SubtitleDownloader
from neural_extractor.validator import extract_video_id, is_mix_url, is_playlist_url


def _detect_browser() -> str | None:
    """Return the name of the first installed browser whose profile directory exists.

    yt-dlp uses the profile directory to extract cookies, so checking for its
    presence is a reliable proxy for whether the browser is installed.
    Supported names: chrome, chromium, firefox, edge, brave, opera, vivaldi, safari.
    """
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", "")).expanduser()
        roaming = Path(os.environ.get("APPDATA", "")).expanduser()
        candidates = [
            ("chrome", local / "Google/Chrome/User Data"),
            ("edge", local / "Microsoft/Edge/User Data"),
            ("brave", local / "BraveSoftware/Brave-Browser/User Data"),
            ("chromium", local / "Chromium/User Data"),
            ("firefox", roaming / "Mozilla/Firefox"),
            ("opera", roaming / "Opera Software/Opera Stable"),
            ("vivaldi", local / "Vivaldi/User Data"),
        ]
    elif sys.platform == "darwin":
        lib = Path.home() / "Library/Application Support"
        candidates = [
            ("chrome", lib / "Google/Chrome"),
            ("edge", lib / "Microsoft Edge"),
            ("brave", lib / "BraveSoftware/Brave-Browser"),
            ("chromium", lib / "Chromium"),
            ("firefox", lib / "Firefox"),
            ("safari", Path.home() / "Library/Safari"),
            ("vivaldi", lib / "Vivaldi"),
        ]
    else:  # Linux / other Unix
        cfg = Path.home() / ".config"
        candidates = [
            ("chrome", cfg / "google-chrome"),
            ("chromium", cfg / "chromium"),
            ("edge", cfg / "microsoft-edge"),
            ("brave", cfg / "BraveSoftware/Brave-Browser"),
            ("firefox", Path.home() / ".mozilla/firefox"),
            ("opera", cfg / "opera"),
            ("vivaldi", cfg / "vivaldi"),
        ]

    for browser, data_dir in candidates:
        if data_dir.exists():
            logger.info(f"Browser cookies: using '{browser}' ({data_dir})")
            return browser

    logger.warning("No browser profile found – downloading without cookies")
    return None


# Cache the result so we only scan the filesystem once per process.
_BROWSER: str | None = _detect_browser()


class Downloader:
    """Handles video downloads using yt-dlp."""

    def __init__(
        self,
        output_dir: Path,
        quality: str = "Highest Resolution",
        download_subtitles: bool = False,
        subtitle_lang: str = "en",
        download_thumbnail: bool = False,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        cookie_file: Path | None = None,
    ):
        """
        Initialize the downloader.

        Args:
            output_dir: Output directory for downloads
            quality: Quality selection string
            download_subtitles: Whether to download subtitles
            subtitle_lang: Subtitle language code
            download_thumbnail: Whether to download thumbnails
            progress_callback: Optional callback for progress updates
            cookie_file: Path to a Netscape-format cookies.txt file exported
                         from the browser.  When provided this takes priority
                         over automatic browser-cookie extraction and works
                         correctly even while the browser is open.
        """
        self.output_dir = Path(output_dir)
        self.quality = quality
        self.download_subtitles = download_subtitles
        self.subtitle_lang = subtitle_lang
        self.download_thumbnail = download_thumbnail
        self.progress_callback = progress_callback
        self.cookie_file = Path(cookie_file) if cookie_file else None
        self.stop_download = False

        # Initialize subtitle downloader if needed
        if self.download_subtitles:
            self.subtitle_downloader = SubtitleDownloader(self.output_dir)
        else:
            self.subtitle_downloader = None

    def build_ydl_options(self, url: str) -> dict[str, Any]:
        """
        Build yt-dlp options for a given URL.

        Args:
            url: YouTube URL

        Returns:
            Dictionary of yt-dlp options
        """
        is_playlist = is_playlist_url(url)
        is_mix_url(url)

        # Output template
        if is_playlist:
            outtmpl = str(self.output_dir / "%(playlist)s" / "%(playlist_index)s-%(title)s.%(ext)s")
        else:
            outtmpl = str(self.output_dir / "%(title)s.%(ext)s")

        # Determine format string based on quality selection
        format_str = "bestvideo+bestaudio/best"  # Default
        if "Audio Only" in self.quality:
            format_str = "bestaudio/best"
        elif "720p" in self.quality:
            format_str = "bestvideo[height<=720]+bestaudio/best"
        elif "480p" in self.quality:
            format_str = "bestvideo[height<=480]+bestaudio/best"
        elif "360p" in self.quality:
            format_str = "bestvideo[height<=360]+bestaudio/best"
        elif "240p" in self.quality:
            format_str = "bestvideo[height<=240]+bestaudio/best"
        elif "144p" in self.quality:
            format_str = "bestvideo[height<=144]+bestaudio/best"

        # Base options with comprehensive rate-limit protection
        ydl_opts: dict[str, Any] = {
            "format": format_str,
            "merge_output_format": "mp4",
            "outtmpl": outtmpl,
            "ignoreerrors": is_playlist,
            "no_warnings": True,
            "quiet": True,
            "ffmpeg_location": str(BIN_DIR),
            # ── Rate-limit protection ────────────────────────────────────
            "sleep_interval": 1,
            "max_sleep_interval": 5,
            "sleep_interval_requests": 1,
            "sleep_interval_subtitles": 2,
            # ── Retry & throttle handling ────────────────────────────────
            "retries": 5,
            "fragment_retries": 10,
            "throttled_rate": 100_000,
            "extractor_retries": 5,
            # ────────────────────────────────────────────────────────────
        }

        # ── Cookie strategy ─────────────────────────────────────────────────
        if self.cookie_file and self.cookie_file.exists():
            ydl_opts["cookiefile"] = str(self.cookie_file)
            # Use the default web client – it matches the browser cookies.
            ydl_opts["extractor_args"] = {"youtube": {"player_client": ["default"]}}
            logger.info(f"Using cookies.txt: {self.cookie_file}")
        else:
            # No cookies → use mobile-web client (least likely to trigger bot)
            ydl_opts["extractor_args"] = {"youtube": {"player_client": ["mweb", "default"]}}
            logger.info("No cookies.txt provided, using mweb client.")
        # ────────────────────────────────────────────────────────────────────

        # Progress hook
        if self.progress_callback:
            ydl_opts["progress_hooks"] = [self.progress_callback]

        # Audio-only mode
        if "Audio Only" in self.quality:
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

        # Subtitle options
        if self.download_subtitles:
            ydl_opts.update(
                {
                    "writesubtitles": True,
                    "subtitleslangs": [self.subtitle_lang],
                    "subtitlesformat": "srt",
                    "writeautomaticsub": True,
                }
            )

        # Thumbnail options
        if self.download_thumbnail:
            ydl_opts.update(
                {
                    "writethumbnail": True,
                }
            )

        # Playlist options
        if is_playlist:
            ydl_opts.update(
                {
                    "playlist": True,
                    "playlistreverse": False,
                    "playlistrandom": False,
                }
            )

        return ydl_opts

    def download(self, url: str) -> dict[str, Any]:
        """
        Download a video or playlist.

        Args:
            url: YouTube URL

        Returns:
            Dictionary with download result information
        """
        if self.stop_download:
            return {"status": "cancelled", "message": "Download cancelled by user"}

        try:
            logger.info(f"Starting download for: {url}")

            ydl_opts = self.build_ydl_options(url)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info first
                info = ydl.extract_info(url, download=False)

                if not info:
                    logger.error("Could not extract info for URL")
                    return {"status": "error", "message": "Could not extract video information"}

                # Handle playlist/mix
                if "entries" in info:
                    return self._download_playlist(ydl, info, url)
                else:
                    return self._download_single(ydl, info, url)

        except Exception as e:
            logger.error(f"Download error: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def _download_single(
        self,
        ydl: yt_dlp.YoutubeDL,
        info: dict[str, Any],
        url: str,
    ) -> dict[str, Any]:
        """
        Download a single video.

        Args:
            ydl: yt-dlp instance
            info: Video info dictionary
            url: Video URL

        Returns:
            Download result dictionary
        """
        logger.info(f"Downloading single video: {info.get('title', 'Unknown')}")

        try:
            retcode = ydl.download([url])
            if retcode != 0:
                logger.error(f"Download failed with code {retcode}")
                return {
                    "status": "error",
                    "message": "Video is mogelijk geblokkeerd of onbeschikbaar. Probeer een cookies.txt bestand in te laden.",
                }
            logger.info(f"Successfully downloaded: {info.get('title', 'Unknown')}")

            # Download subtitles if requested
            subtitle_paths = None
            if self.download_subtitles and self.subtitle_downloader:
                video_id = info.get("id") or extract_video_id(url)
                if video_id:
                    try:
                        subtitle_paths = self.subtitle_downloader.download_subtitles(
                            video_id=video_id,
                            video_title=info.get("title"),
                            language=self.subtitle_lang,
                            formats=["vtt", "srt"],
                        )
                        if subtitle_paths:
                            logger.info(f"Downloaded subtitles: {subtitle_paths}")
                    except Exception as e:
                        logger.warning(f"Failed to download subtitles: {e}")

            return {
                "status": "success",
                "title": info.get("title"),
                "video_id": info.get("id"),
                "url": url,
                "subtitle_paths": subtitle_paths,
            }
        except Exception as e:
            logger.error(f"Error downloading video: {e}")
            return {"status": "error", "message": str(e)}

    def _download_playlist(
        self,
        ydl: yt_dlp.YoutubeDL,
        info: dict[str, Any],
        url: str,
    ) -> dict[str, Any]:
        """
        Download a playlist or mix.

        Args:
            ydl: yt-dlp instance
            info: Playlist info dictionary
            url: Playlist URL

        Returns:
            Download result dictionary
        """
        is_mix = is_mix_url(url)
        entries = list(info.get("entries", []))

        # Filter out None entries and duplicates
        seen_ids: set[str] = set()
        filtered_entries: list[dict[str, Any]] = []

        for entry in entries:
            if not entry:
                continue

            vid = entry.get("id")
            if vid and vid not in seen_ids:
                filtered_entries.append(entry)
                seen_ids.add(vid)

            # Limit Mix videos
            if is_mix and len(filtered_entries) >= MAX_PLAYLIST_VIDEOS:
                break

        total_videos = len(filtered_entries)
        logger.info(f"Processing {total_videos} videos from playlist/mix")

        downloaded = 0
        failed = 0

        for idx, entry in enumerate(filtered_entries, 1):
            if self.stop_download:
                logger.info("Download stopped by user")
                break

            video_id = entry.get("id")
            if not video_id:
                continue

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            title = entry.get("title", "Unknown")

            logger.info(f"Downloading {idx}/{total_videos}: {title}")

            # Sleep between playlist items to avoid rate-limiting
            if idx > 1:
                wait = random.uniform(2.0, 6.0)
                logger.info(f"Rate-limit bescherming: {wait:.1f}s wachten...")
                time.sleep(wait)

            try:
                ydl.download([video_url])
                downloaded += 1
                logger.info(f"Successfully downloaded: {title}")

                # Download subtitles if requested
                if self.download_subtitles and self.subtitle_downloader:
                    try:
                        subtitle_paths = self.subtitle_downloader.download_subtitles(
                            video_id=video_id,
                            video_title=title,
                            language=self.subtitle_lang,
                            formats=["vtt", "srt"],
                        )
                        if subtitle_paths:
                            logger.info(f"Downloaded subtitles for {title}: {subtitle_paths}")
                    except Exception as e:
                        logger.warning(f"Failed to download subtitles for {title}: {e}")
            except Exception as e:
                failed += 1
                logger.error(f"Error downloading {title}: {e}")

        return {
            "status": "success",
            "downloaded": downloaded,
            "failed": failed,
            "total": total_videos,
        }

    def cancel(self) -> None:
        """Cancel the current download."""
        self.stop_download = True
        logger.info("Download cancellation requested")
