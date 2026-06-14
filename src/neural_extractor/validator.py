"""URL validation and parsing utilities."""

import re
from urllib.parse import parse_qs, urlparse
from typing import Optional

from neural_extractor.config import YOUTUBE_URL_REGEX


def validate_youtube_url(url: str) -> bool:
    """
    Validate if a URL is a valid YouTube URL.
    
    Args:
        url: URL string to validate
    
    Returns:
        True if valid YouTube URL, False otherwise
    """
    if not url or not isinstance(url, str):
        return False
    
    match = re.match(YOUTUBE_URL_REGEX, url.strip())
    return match is not None


def extract_video_id(url: str) -> Optional[str]:
    """
    Extract video ID from a YouTube URL.
    
    Args:
        url: YouTube URL
    
    Returns:
        Video ID if found, None otherwise
    """
    if not url:
        return None
    
    try:
        if "youtu.be" in url:
            video_id = urlparse(url).path.strip("/")
            return video_id if video_id else None
        else:
            parsed_url = urlparse(url)
            video_ids = parse_qs(parsed_url.query).get("v", [])
            return video_ids[0] if video_ids else None
    except Exception:
        return None


def is_playlist_url(url: str) -> bool:
    """
    Check if URL is a playlist or mix.
    
    Args:
        url: YouTube URL
    
    Returns:
        True if playlist/mix, False otherwise
    """
    if not url:
        return False
    
    return "playlist" in url or "list=" in url or "mix" in url or "RD" in url


def is_mix_url(url: str) -> bool:
    """
    Check if URL is a YouTube Mix.
    
    Args:
        url: YouTube URL
    
    Returns:
        True if Mix, False otherwise
    """
    if not url:
        return False
    
    return "mix" in url or "RD" in url

