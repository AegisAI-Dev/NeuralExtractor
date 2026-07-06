from pathlib import Path

from neural_extractor_v3.core.auth import AuthStrategy
from neural_extractor_v3.core.downloader import DownloadEngine
from neural_extractor_v3.models import DownloadOptions, MediaMode, PlaylistMode


def make_engine(tmp_path: Path, **overrides) -> DownloadEngine:
    options = DownloadOptions(output_dir=tmp_path, **overrides)
    return DownloadEngine(options)


def test_video_quality_generates_height_limited_selector(tmp_path):
    engine = make_engine(tmp_path, media_mode=MediaMode.VIDEO, quality="1080p Full HD")
    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123")

    assert "height<=1080" in opts["format"]
    assert opts["merge_output_format"] == "mp4"
    assert opts["noplaylist"] is True


def test_mp3_mode_extracts_audio_and_embeds_thumbnail(tmp_path):
    engine = make_engine(
        tmp_path,
        media_mode=MediaMode.AUDIO_MP3,
        thumbnail=True,
        embed_thumbnail=True,
        audio_quality="320",
    )
    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123")
    post_keys = [processor["key"] for processor in opts["postprocessors"]]

    assert opts["format"] == "bestaudio/best"
    assert "FFmpegExtractAudio" in post_keys
    assert "EmbedThumbnail" in post_keys
    assert opts["writethumbnail"] is True


def test_subtitle_mode_writes_srt_and_skips_media(tmp_path):
    engine = make_engine(
        tmp_path,
        media_mode=MediaMode.SUBTITLES_ONLY,
        subtitle_language="nl",
        subtitles=True,
    )
    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123")
    post_keys = [processor["key"] for processor in opts["postprocessors"]]

    assert opts["skip_download"] is True
    assert opts["subtitleslangs"] == ["nl"]
    assert opts["subtitlesformat"].startswith("srt")
    assert "FFmpegSubtitlesConvertor" in post_keys


def test_full_playlist_keeps_playlist_enabled(tmp_path):
    engine = make_engine(tmp_path, playlist_mode=PlaylistMode.FULL)
    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123&list=PL42")

    assert opts["noplaylist"] is False
    assert "%(playlist" in opts["outtmpl"]


def test_auth_strategy_is_merged_into_ydl_options(tmp_path):
    engine = make_engine(tmp_path)
    auth = AuthStrategy(
        kind="browser",
        display_name="Chrome",
        attempted_auth=True,
        ydl_options={
            "cookiesfrombrowser": ("chrome",),
            "extractor_args": {"youtube": {"player_client": ["default"]}},
        },
    )

    opts = engine.build_ydl_options("https://www.youtube.com/watch?v=abc123", auth)

    assert opts["cookiesfrombrowser"] == ("chrome",)
    assert opts["extractor_args"] == {"youtube": {"player_client": ["default"]}}
