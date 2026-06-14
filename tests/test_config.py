"""Tests for configuration module."""

from pathlib import Path

import pytest

from neural_extractor.config import (
    ASSETS_DIR,
    DEFAULT_OUTPUT,
    DEFAULT_QUALITY,
    DEFAULT_SUBTITLE_LANG,
    QUALITY_OPTIONS,
    SUBTITLE_LANGUAGES,
    VERSION,
)


class TestConfig:
    """Tests for configuration constants."""
    
    def test_version(self) -> None:
        """Test that version is set."""
        assert VERSION == "0.1.0"
    
    def test_default_output(self) -> None:
        """Test that default output is a Path."""
        assert isinstance(DEFAULT_OUTPUT, Path)
        assert DEFAULT_OUTPUT.name == "Downloads"
    
    def test_default_quality(self) -> None:
        """Test that default quality is valid."""
        assert DEFAULT_QUALITY in QUALITY_OPTIONS
    
    def test_default_subtitle_lang(self) -> None:
        """Test that default subtitle language is valid."""
        assert DEFAULT_SUBTITLE_LANG in SUBTITLE_LANGUAGES
    
    def test_quality_options_not_empty(self) -> None:
        """Test that quality options list is not empty."""
        assert len(QUALITY_OPTIONS) > 0
        assert "Highest Resolution" in QUALITY_OPTIONS
        assert "Audio Only (MP3)" in QUALITY_OPTIONS
    
    def test_subtitle_languages_not_empty(self) -> None:
        """Test that subtitle languages list is not empty."""
        assert len(SUBTITLE_LANGUAGES) > 0
        assert "en" in SUBTITLE_LANGUAGES
    
    def test_assets_dir_exists(self) -> None:
        """Test that assets directory path is valid."""
        assert isinstance(ASSETS_DIR, Path)

