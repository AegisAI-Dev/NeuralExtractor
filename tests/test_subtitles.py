"""Tests for subtitle download and normalization."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neural_extractor.subtitles import SubtitleDownloader


class TestSubtitleDownloader:
    """Tests for SubtitleDownloader class."""
    
    def test_init(self, tmp_path: Path) -> None:
        """Test SubtitleDownloader initialization."""
        downloader = SubtitleDownloader(tmp_path)
        assert downloader.output_dir == tmp_path
        assert tmp_path.exists()
    
    def test_sanitize_filename(self, tmp_path: Path) -> None:
        """Test filename sanitization."""
        downloader = SubtitleDownloader(tmp_path)
        
        # Normal filename
        assert downloader._sanitize_filename("My Video") == "My Video"
        
        # Filename with special chars
        result = downloader._sanitize_filename("My/Video:Title?<test>")
        assert "/" not in result
        assert ":" not in result
        assert "?" not in result
        assert "<" not in result
        assert ">" not in result
        
        # Path traversal attempt
        result = downloader._sanitize_filename("../../../etc/passwd")
        assert "../" not in result
        
        # Long filename
        long_name = "a" * 300
        result = downloader._sanitize_filename(long_name)
        assert len(result) <= 200
    
    def test_format_timestamp(self, tmp_path: Path) -> None:
        """Test timestamp formatting for WebVTT."""
        downloader = SubtitleDownloader(tmp_path)
        
        # Test various timestamps
        assert downloader._format_timestamp(0) == "00:00:00.000"
        assert downloader._format_timestamp(65.5) == "00:01:05.500"
        assert downloader._format_timestamp(3661.123) == "01:01:01.123"
    
    def test_format_timestamp_srt(self, tmp_path: Path) -> None:
        """Test timestamp formatting for SRT."""
        downloader = SubtitleDownloader(tmp_path)
        
        # Test various timestamps
        assert downloader._format_timestamp_srt(0) == "00:00:00,000"
        assert downloader._format_timestamp_srt(65.5) == "00:01:05,500"
        assert downloader._format_timestamp_srt(3661.123) == "01:01:01,123"
    
    def test_write_vtt(self, tmp_path: Path) -> None:
        """Test writing WebVTT file."""
        downloader = SubtitleDownloader(tmp_path)
        
        transcript_data = [
            {"text": "Hello world", "start": 0.0, "duration": 5.0},
            {"text": "This is a test", "start": 5.0, "duration": 3.0},
        ]
        
        vtt_path = tmp_path / "test.vtt"
        downloader._write_vtt(vtt_path, transcript_data)
        
        assert vtt_path.exists()
        content = vtt_path.read_text(encoding="utf-8")
        assert "WEBVTT" in content
        assert "Hello world" in content
        assert "This is a test" in content
        assert "00:00:00.000 --> 00:00:05.000" in content
    
    def test_write_srt(self, tmp_path: Path) -> None:
        """Test writing SRT file."""
        downloader = SubtitleDownloader(tmp_path)
        
        transcript_data = [
            {"text": "Hello world", "start": 0.0, "duration": 5.0},
            {"text": "This is a test", "start": 5.0, "duration": 3.0},
        ]
        
        srt_path = tmp_path / "test.srt"
        downloader._write_srt(srt_path, transcript_data)
        
        assert srt_path.exists()
        content = srt_path.read_text(encoding="utf-8")
        assert "1" in content
        assert "2" in content
        assert "Hello world" in content
        assert "00:00:00,000 --> 00:00:05,000" in content
    
    @patch("neural_extractor.subtitles.yt_dlp.YoutubeDL")
    def test_download_via_yt_dlp_success(self, mock_ydl_class: MagicMock, tmp_path: Path) -> None:
        """Test successful subtitle download via yt-dlp."""
        downloader = SubtitleDownloader(tmp_path)
        
        # Mock yt-dlp
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        
        mock_info = {
            "title": "Test Video",
            "id": "dQw4w9WgXcQ",
            "subtitles": {"en": [{"ext": "srt", "url": "http://example.com/sub.srt"}]},
            "automatic_captions": {},
        }
        mock_ydl.extract_info.return_value = mock_info
        
        result = downloader._download_via_yt_dlp("dQw4w9WgXcQ", "en")
        
        # Should attempt to download
        mock_ydl.download.assert_called_once()
    
    @patch("neural_extractor.subtitles.YouTubeTranscriptApi")
    def test_download_via_transcript_api_success(
        self, mock_api: MagicMock, tmp_path: Path
    ) -> None:
        """Test successful subtitle download via transcript API."""
        downloader = SubtitleDownloader(tmp_path)
        
        # Mock transcript API
        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 2.0},
            {"text": "World", "start": 2.0, "duration": 2.0},
        ]
        
        mock_transcript_list = MagicMock()
        mock_transcript_list.find_transcript.return_value = mock_transcript
        mock_api.list_transcripts.return_value = mock_transcript_list
        
        result = downloader._download_via_transcript_api(
            "dQw4w9WgXcQ", "en", "Test Video", ["vtt", "srt"]
        )
        
        assert result is not None
        assert "vtt" in result
        assert "srt" in result
        assert result["vtt"].exists()
        assert result["srt"].exists()
    
    @patch("neural_extractor.subtitles.YouTubeTranscriptApi")
    def test_download_via_transcript_api_fallback(
        self, mock_api: MagicMock, tmp_path: Path
    ) -> None:
        """Test fallback to ASR translation."""
        downloader = SubtitleDownloader(tmp_path)
        
        # Mock transcript API with ASR fallback
        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 2.0},
        ]
        mock_transcript.is_generated = True
        mock_transcript.translate.return_value = mock_transcript
        
        mock_transcript_list = MagicMock()
        # First call (find_transcript) raises NoTranscriptFound
        mock_transcript_list.find_transcript.side_effect = Exception("Not found")
        # Manual transcripts empty, but generated transcripts available
        mock_transcript_list.__iter__.return_value = [mock_transcript]
        
        mock_api.list_transcripts.return_value = mock_transcript_list
        
        result = downloader._download_via_transcript_api(
            "dQw4w9WgXcQ", "nl", "Test Video", ["vtt"]
        )
        
        # Should attempt translation
        mock_transcript.translate.assert_called_once_with("nl")

