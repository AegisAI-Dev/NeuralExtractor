"""Neural Extractor V3 package."""

import os

# The application never loads arbitrary yt-dlp plugins.  Set this before any
# core module can import yt-dlp; the worker also reasserts it defensively.
os.environ["YTDLP_NO_PLUGINS"] = "1"

from neural_extractor_v3.config import APP_NAME, VERSION

__all__ = ["APP_NAME", "VERSION"]
