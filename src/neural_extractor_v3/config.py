"""Configuration constants for Neural Extractor V3."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Neural Extractor V3"
VERSION = "3.0.2"
BUILD_LABEL = "http403-retry-bootstrap-auto-updater"
WINDOW_TITLE = f"{APP_NAME} {VERSION}"

GITHUB_REPO = "AegisAI-Dev/NeuralExtractor"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
UPDATE_CHECK_TIMEOUT_SECONDS = 8

QUALITY_PRESETS: dict[str, int | None] = {
    "Best available": None,
    "2160p 4K": 2160,
    "1440p QHD": 1440,
    "1080p Full HD": 1080,
    "720p HD": 720,
    "480p": 480,
    "360p": 360,
}

YTDLP_SOCKET_TIMEOUT_SECONDS = 30
YOUTUBE_EJS_REMOTE_COMPONENT = "ejs:github"
YOUTUBE_REMOTE_COMPONENTS = [YOUTUBE_EJS_REMOTE_COMPONENT]

AUDIO_BITRATES = ["320", "256", "192", "128"]

SUBTITLE_LANGUAGES: dict[str, str] = {
    "nl": "Dutch",
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "tr": "Turkish",
    "ar": "Arabic",
    "ja": "Japanese",
    "ko": "Korean",
    "zh-Hans": "Chinese Simplified",
}

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}

THROTTLE_SAFE_OPTIONS = {
    "socket_timeout": YTDLP_SOCKET_TIMEOUT_SECONDS,
    "sleep_interval": 1,
    "max_sleep_interval": 5,
    "sleep_interval_requests": 1,
    "sleep_interval_subtitles": 2,
    "retries": 5,
    "fragment_retries": 10,
    "extractor_retries": 5,
    "throttled_rate": 100_000,
}


def base_dir() -> Path:
    """Return project root in development or the bundle temp dir in PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    return base_dir() / "assets"


def bin_dir() -> Path:
    return base_dir() / "bin"


def app_data_dir() -> Path:
    if sys.platform == "win32":
        local_app_data = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )
        data_dir = local_app_data / "NeuralExtractorV3"
    else:
        data_dir = Path.home() / ".local" / "share" / "NeuralExtractorV3"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
