"""Configuration constants for Neural Extractor."""

import os
from pathlib import Path
import sys
from typing import Final

# Version
VERSION: Final[str] = "2.0"
GITHUB_REPO: Final[str] = "NeuralShield/NeuralExtractor"  # Update dit zodra de repo openbaar is

# Colors
BG_COLOR: Final[str] = "#1a2233"  # Navy blue
FG_COLOR: Final[str] = "#ffffff"  # White
ACCENT_COLOR: Final[str] = "#1abc9c"  # Teal
BUTTON_COLOR: Final[str] = "#ff9900"  # Orange
BUTTON_FG: Final[str] = "#000000"  # Black
PROGRESS_COLOR: Final[str] = "#1abc9c"  # Teal
INPUT_BG_COLOR: Final[str] = "#2c3e50"  # Darker blue for input

# Window settings
WINDOW_TITLE: Final[str] = "Neural Extractor"
WINDOW_GEOMETRY: Final[str] = "800x600"
WINDOW_MIN_SIZE: Final[tuple[int, int]] = (700, 500)

# Paths
def get_base_dir() -> Path:
    """Return project root (development) or _MEIPASS (frozen)."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent.parent

def get_data_dir() -> Path:
    """Return user-writable data directory for logs etc."""
    data_dir = Path(os.environ.get("APPDATA", Path.home())) / "NeuralExtractor"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

def get_assets_dir() -> Path:
    """Get the assets directory path."""
    assets_dir = get_base_dir() / "assets"
    if not assets_dir.exists():
        # Fallback: look in current directory
        assets_dir = Path("assets")
    return assets_dir.resolve()

def get_bin_dir() -> Path:
    """Get the bin directory path for executables like ffmpeg."""
    bin_dir = get_base_dir() / "bin"
    if not bin_dir.exists():
        bin_dir = Path("bin")
    return bin_dir.resolve()

ASSETS_DIR: Final[Path] = get_assets_dir()
BIN_DIR: Final[Path] = get_bin_dir()
ICON_ICO: Final[Path] = ASSETS_DIR / "NeuralExtractoricon.ico"  # Windows .ico (multi-size 16-512 px)
ICON_PNG: Final[Path] = ASSETS_DIR / "NeuralExtractorIcon.png"  # macOS / Linux .png (512×512)

# Defaults
DEFAULT_OUTPUT: Final[Path] = Path.home() / "Downloads"
DEFAULT_QUALITY: Final[str] = "Highest Resolution"
DEFAULT_SUBTITLE_LANG: Final[str] = "en"

# Quality options
QUALITY_OPTIONS: Final[list[str]] = [
    "Highest Resolution",
    "720p HD",
    "480p",
    "360p",
    "240p",
    "144p",
    "Audio Only (MP3)",
]

# Subtitle languages
SUBTITLE_LANGUAGES: Final[list[str]] = [
    "en", "nl", "de", "fr", "es", "it", "tr", "ru", "ar", "zh-Hans", "ja", "ko"
]

# Limits
MAX_PLAYLIST_VIDEOS: Final[int] = 100
THUMBNAIL_TIMEOUT: Final[int] = 10
ANIMATION_FPS: Final[int] = 60  # Target FPS for animations
ANIMATION_INTERVAL_MS: Final[int] = 16  # ~60 FPS

# YouTube URL patterns
YOUTUBE_URL_REGEX: Final[str] = (
    r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/'
    r'(watch\?v=|playlist\?list=|mix\/|watch\?v=.*&list=).*$'
)

# Thumbnail URLs
THUMBNAIL_BASE_URL: Final[str] = "https://img.youtube.com/vi/{video_id}/"
THUMBNAIL_OPTIONS: Final[list[str]] = ["maxresdefault.jpg", "hqdefault.jpg"]

