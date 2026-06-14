"""Thumbnail download functionality."""

import re
from pathlib import Path
from typing import Optional

import requests

from neural_extractor.config import (
    THUMBNAIL_BASE_URL,
    THUMBNAIL_OPTIONS,
    THUMBNAIL_TIMEOUT,
)
from neural_extractor.logger import logger


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent path traversal and invalid characters.
    
    Args:
        filename: Original filename
    
    Returns:
        Sanitized filename safe for filesystem use
    """
    # Remove path separators and dangerous characters
    sanitized = re.sub(r'[^\w\-_\. ]', '_', filename)
    # Remove leading/trailing dots and spaces
    sanitized = sanitized.strip('. ')
    # Limit length
    if len(sanitized) > 200:
        sanitized = sanitized[:200]
    return sanitized


def download_thumbnail(
    video_id: str,
    output_dir: Path,
    title: Optional[str] = None,
) -> Optional[Path]:
    """
    Download YouTube thumbnail for a video.
    
    Args:
        video_id: YouTube video ID
        output_dir: Directory to save thumbnail
        title: Optional video title for filename
    
    Returns:
        Path to downloaded thumbnail if successful, None otherwise
    """
    if not video_id:
        logger.warning("No video ID provided for thumbnail download")
        return None
    
    if not output_dir.exists():
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create output directory: {e}")
            return None
    
    # Try different thumbnail resolutions
    for thumb_option in THUMBNAIL_OPTIONS:
        url = THUMBNAIL_BASE_URL.format(video_id=video_id) + thumb_option
        
        try:
            response = requests.get(url, timeout=THUMBNAIL_TIMEOUT)
            
            if response.status_code == 200 and response.content:
                # Generate safe filename
                safe_title = sanitize_filename(title) if title else video_id
                filename = f"{safe_title}_thumbnail.jpg"
                output_path = output_dir / filename
                
                # Write file
                with open(output_path, "wb") as f:
                    f.write(response.content)
                
                logger.info(f"Thumbnail saved: {output_path}")
                return output_path
                
        except requests.exceptions.RequestException as e:
            logger.debug(f"Failed to download {thumb_option}: {e}")
            continue
        except Exception as e:
            logger.error(f"Error downloading thumbnail: {e}")
            continue
    
    logger.warning(f"Thumbnail not found for video {video_id}")
    return None

