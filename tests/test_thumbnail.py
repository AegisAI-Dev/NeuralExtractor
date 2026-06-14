"""Tests for thumbnail download functionality."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neural_extractor.thumbnail import download_thumbnail, sanitize_filename


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""
    
    def test_sanitize_normal_filename(self) -> None:
        """Test sanitizing a normal filename."""
        filename = "My Video Title"
        result = sanitize_filename(filename)
        assert result == "My Video Title"
    
    def test_sanitize_filename_with_special_chars(self) -> None:
        """Test sanitizing filename with special characters."""
        filename = "My/Video:Title?<test>"
        result = sanitize_filename(filename)
        assert ":" not in result
        assert "/" not in result
        assert "?" not in result
        assert "<" not in result
        assert ">" not in result
    
    def test_sanitize_path_traversal(self) -> None:
        """Test that path traversal attempts are sanitized."""
        filename = "../../etc/passwd"
        result = sanitize_filename(filename)
        assert "../" not in result
        assert result.count("_") >= 2  # Should have replaced ../ with _
    
    def test_sanitize_empty_filename(self) -> None:
        """Test sanitizing empty filename."""
        result = sanitize_filename("")
        assert result == ""
    
    def test_sanitize_long_filename(self) -> None:
        """Test that long filenames are truncated."""
        long_filename = "a" * 300
        result = sanitize_filename(long_filename)
        assert len(result) <= 200


class TestDownloadThumbnail:
    """Tests for download_thumbnail function."""
    
    @patch("neural_extractor.thumbnail.requests.get")
    def test_download_thumbnail_success(self, mock_get: MagicMock) -> None:
        """Test successful thumbnail download."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake image data"
        mock_get.return_value = mock_response
        
        # Create temp directory
        output_dir = Path("/tmp/test_thumbnails")
        output_dir.mkdir(exist_ok=True)
        
        try:
            result = download_thumbnail("dQw4w9WgXcQ", output_dir, "Test Video")
            assert result is not None
            assert result.exists()
            assert result.suffix == ".jpg"
        finally:
            # Cleanup
            if result and result.exists():
                result.unlink()
            if output_dir.exists():
                output_dir.rmdir()
    
    @patch("neural_extractor.thumbnail.requests.get")
    def test_download_thumbnail_not_found(self, mock_get: MagicMock) -> None:
        """Test thumbnail download when not found."""
        # Mock 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response
        
        output_dir = Path("/tmp/test_thumbnails")
        output_dir.mkdir(exist_ok=True)
        
        try:
            result = download_thumbnail("invalid_id", output_dir)
            assert result is None
        finally:
            if output_dir.exists():
                output_dir.rmdir()
    
    @patch("neural_extractor.thumbnail.requests.get")
    def test_download_thumbnail_timeout(self, mock_get: MagicMock) -> None:
        """Test thumbnail download with timeout."""
        import requests
        
        # Mock timeout exception
        mock_get.side_effect = requests.exceptions.Timeout("Connection timeout")
        
        output_dir = Path("/tmp/test_thumbnails")
        output_dir.mkdir(exist_ok=True)
        
        try:
            result = download_thumbnail("dQw4w9WgXcQ", output_dir)
            assert result is None
        finally:
            if output_dir.exists():
                output_dir.rmdir()
    
    def test_download_thumbnail_empty_video_id(self) -> None:
        """Test thumbnail download with empty video ID."""
        output_dir = Path("/tmp/test_thumbnails")
        output_dir.mkdir(exist_ok=True)
        
        try:
            result = download_thumbnail("", output_dir)
            assert result is None
        finally:
            if output_dir.exists():
                output_dir.rmdir()

