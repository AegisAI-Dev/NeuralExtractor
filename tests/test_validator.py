"""Tests for URL validation and parsing."""


from neural_extractor.validator import (
    extract_video_id,
    is_mix_url,
    is_playlist_url,
    validate_youtube_url,
)


class TestValidateYouTubeURL:
    """Tests for validate_youtube_url function."""

    def test_valid_single_video_url(self) -> None:
        """Test validation of single video URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert validate_youtube_url(url) is True

    def test_valid_short_url(self) -> None:
        """Test validation of short YouTube URL."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert validate_youtube_url(url) is True

    def test_valid_playlist_url(self) -> None:
        """Test validation of playlist URL."""
        url = "https://www.youtube.com/playlist?list=PLrAXtmRdnEQy6nuLMH7Pz0lO2wQ5Q8j8K"
        assert validate_youtube_url(url) is True

    def test_valid_mix_url(self) -> None:
        """Test validation of mix URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ"
        assert validate_youtube_url(url) is True

    def test_invalid_url(self) -> None:
        """Test validation of invalid URL."""
        url = "https://www.google.com"
        assert validate_youtube_url(url) is False

    def test_empty_url(self) -> None:
        """Test validation of empty URL."""
        assert validate_youtube_url("") is False
        assert validate_youtube_url(None) is False  # type: ignore[arg-type]


class TestExtractVideoID:
    """Tests for extract_video_id function."""

    def test_extract_from_standard_url(self) -> None:
        """Test extracting video ID from standard URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_extract_from_short_url(self) -> None:
        """Test extracting video ID from short URL."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_extract_from_url_with_params(self) -> None:
        """Test extracting video ID from URL with additional parameters."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmRdnEQy6nuLMH7Pz0lO2wQ5Q8j8K"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_extract_from_invalid_url(self) -> None:
        """Test extracting video ID from invalid URL."""
        url = "https://www.google.com"
        assert extract_video_id(url) is None

    def test_extract_from_empty_url(self) -> None:
        """Test extracting video ID from empty URL."""
        assert extract_video_id("") is None


class TestIsPlaylistURL:
    """Tests for is_playlist_url function."""

    def test_playlist_url(self) -> None:
        """Test detection of playlist URL."""
        url = "https://www.youtube.com/playlist?list=PLrAXtmRdnEQy6nuLMH7Pz0lO2wQ5Q8j8K"
        assert is_playlist_url(url) is True

    def test_mix_url(self) -> None:
        """Test detection of mix URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ"
        assert is_playlist_url(url) is True

    def test_single_video_url(self) -> None:
        """Test that single video URL is not detected as playlist."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert is_playlist_url(url) is False


class TestIsMixURL:
    """Tests for is_mix_url function."""

    def test_mix_url(self) -> None:
        """Test detection of mix URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ"
        assert is_mix_url(url) is True

    def test_rd_url(self) -> None:
        """Test detection of RD (Radio) URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ"
        assert is_mix_url(url) is True

    def test_regular_playlist_url(self) -> None:
        """Test that regular playlist URL is not detected as mix."""
        url = "https://www.youtube.com/playlist?list=PLrAXtmRdnEQy6nuLMH7Pz0lO2wQ5Q8j8K"
        assert is_mix_url(url) is False
