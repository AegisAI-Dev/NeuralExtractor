"""Subtitle download and normalization functionality.

This module handles:
- Native/auto subtitle download via yt-dlp
- Fallback to youtube-transcript-api for translations
- Conversion to WebVTT and SRT formats
- Normalization of subtitle content
"""

import re
from pathlib import Path
from typing import Any

import yt_dlp

# Try to import youtube-transcript-api (optional dependency)
try:
    from youtube_transcript_api import (
        TranscriptList,
        TranscriptsDisabled,
        YouTubeTranscriptApi,
    )
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
    )
    from youtube_transcript_api._errors import (
        TranscriptsDisabled as TranscriptsDisabledError,
    )

    HAS_TRANSCRIPT_API = True
except ImportError:
    # Fallback if youtube-transcript-api is not available
    HAS_TRANSCRIPT_API = False
    TranscriptList = None  # type: ignore
    TranscriptsDisabled = None  # type: ignore
    YouTubeTranscriptApi = None  # type: ignore
    NoTranscriptFound = Exception  # type: ignore
    TranscriptsDisabledError = Exception  # type: ignore

from neural_extractor.logger import logger


class SubtitleDownloader:
    """Handles subtitle download and normalization."""

    def __init__(self, output_dir: Path) -> None:
        """
        Initialize the subtitle downloader.

        Args:
            output_dir: Directory to save subtitles
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download_subtitles(
        self,
        video_id: str,
        video_title: str | None = None,
        language: str = "en",
        formats: list[str] = None,
    ) -> dict[str, Path | None]:
        """
        Download subtitles for a video with fallback support.

        Strategy:
        1. Try native/auto subtitles via yt-dlp
        2. If desired language missing but ASR available, use youtube-transcript-api
        3. Normalize to WebVTT and SRT

        Args:
            video_id: YouTube video ID
            video_title: Optional video title for filename
            language: Desired language code (e.g., 'en', 'nl', 'de')
            formats: List of formats to generate (default: ['vtt', 'srt'])

        Returns:
            Dictionary with format -> path mapping (e.g., {'vtt': Path, 'srt': Path})
        """
        if formats is None:
            formats = ["vtt", "srt"]

        results: dict[str, Path | None] = {fmt: None for fmt in formats}

        # Step 1: Try yt-dlp for native/auto subtitles
        logger.info(f"Attempting to download subtitles via yt-dlp for video {video_id}")
        yt_dlp_result = self._download_via_yt_dlp(video_id, language)

        if yt_dlp_result:
            # Convert to requested formats
            for fmt in formats:
                if fmt == "vtt" and yt_dlp_result.get("vtt"):
                    results["vtt"] = yt_dlp_result["vtt"]
                elif fmt == "srt" and yt_dlp_result.get("srt"):
                    results["srt"] = yt_dlp_result["srt"]
                elif fmt == "vtt" and yt_dlp_result.get("srt"):
                    # Convert SRT to VTT
                    results["vtt"] = self._convert_srt_to_vtt(
                        yt_dlp_result["srt"], video_id, video_title
                    )
                elif fmt == "srt" and yt_dlp_result.get("vtt"):
                    # Convert VTT to SRT
                    results["srt"] = self._convert_vtt_to_srt(
                        yt_dlp_result["vtt"], video_id, video_title
                    )

            # If we got what we need, return
            if any(results.values()):
                logger.info(f"Successfully downloaded subtitles via yt-dlp for {video_id}")
                return results

        # Step 2: Fallback to youtube-transcript-api
        if HAS_TRANSCRIPT_API:
            logger.info(f"Falling back to youtube-transcript-api for video {video_id}")
            transcript_result = self._download_via_transcript_api(
                video_id, language, video_title, formats
            )

            if transcript_result:
                results.update(transcript_result)
                logger.info(f"Successfully downloaded subtitles via transcript-api for {video_id}")
        else:
            logger.warning("youtube-transcript-api not available, skipping fallback")

        return results

    def _download_via_yt_dlp(self, video_id: str, language: str) -> dict[str, Path] | None:
        """
        Download subtitles using yt-dlp.

        Args:
            video_id: YouTube video ID
            language: Desired language code

        Returns:
            Dictionary with format -> path mapping, or None if failed
        """
        url = f"https://www.youtube.com/watch?v={video_id}"

        try:
            # Configure yt-dlp to download subtitles
            ydl_opts = {
                "writesubtitles": True,
                "subtitleslangs": [language],
                "subtitlesformat": "srt/vtt",  # Try both formats
                "writeautomaticsub": True,  # Include auto-generated subtitles
                "skip_download": True,  # Only download subtitles
                "quiet": True,
                "no_warnings": True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info to get available subtitle languages
                info = ydl.extract_info(url, download=False)

                if not info:
                    return None

                # Check available subtitles
                subtitles = info.get("subtitles", {})
                automatic_captions = info.get("automatic_captions", {})

                # Combine both sources
                all_subtitles = {**subtitles, **automatic_captions}

                if language not in all_subtitles:
                    logger.debug(f"Language {language} not available via yt-dlp for {video_id}")
                    # Check if we have ASR in another language
                    if automatic_captions:
                        logger.debug(f"ASR available in: {list(automatic_captions.keys())}")
                    return None

                # Download subtitles
                ydl.download([url])

                # Find downloaded subtitle files
                # yt-dlp saves subtitles with pattern: {title}.{lang}.{ext}
                video_title = info.get("title", video_id)
                safe_title = self._sanitize_filename(video_title)

                subtitle_files: dict[str, Path] = {}

                # Look for SRT and VTT files in output directory
                # yt-dlp may save with different patterns
                patterns = [
                    f"{safe_title}.{language}.srt",
                    f"{safe_title}.{language}.vtt",
                    f"{safe_title}.srt",
                    f"{safe_title}.vtt",
                ]

                for pattern in patterns:
                    subtitle_path = self.output_dir / pattern
                    if subtitle_path.exists():
                        ext = subtitle_path.suffix[1:]  # Remove the dot
                        if ext not in subtitle_files:
                            subtitle_files[ext] = subtitle_path

                # Also search for any subtitle files matching the pattern
                if not subtitle_files:
                    for subtitle_file in self.output_dir.glob(f"*.{language}.srt"):
                        subtitle_files["srt"] = subtitle_file
                        break
                    for subtitle_file in self.output_dir.glob(f"*.{language}.vtt"):
                        subtitle_files["vtt"] = subtitle_file
                        break

                if subtitle_files:
                    return subtitle_files

        except Exception as e:
            logger.warning(f"Failed to download subtitles via yt-dlp: {e}")

        return None

    def _download_via_transcript_api(
        self,
        video_id: str,
        language: str,
        video_title: str | None = None,
        formats: list[str] = None,
    ) -> dict[str, Path] | None:
        """
        Download subtitles using youtube-transcript-api as fallback.

        This is used when:
        - Native subtitles are not available in the desired language
        - ASR (auto-generated) subtitles exist and can be translated

        Args:
            video_id: YouTube video ID
            language: Desired language code
            video_title: Optional video title for filename
            formats: List of formats to generate

        Returns:
            Dictionary with format -> path mapping, or None if failed
        """
        if formats is None:
            formats = ["vtt", "srt"]

        if not HAS_TRANSCRIPT_API:
            logger.warning("youtube-transcript-api not available")
            return None

        try:
            # Get available transcripts
            transcript_list: TranscriptList = YouTubeTranscriptApi.list_transcripts(  # type: ignore
                video_id
            )

            # Try to get transcript in desired language
            transcript = None
            try:
                transcript = transcript_list.find_transcript([language])  # type: ignore
            except (NoTranscriptFound, Exception):  # type: ignore
                # Try to find manually created transcript in any language
                try:
                    manual_transcripts = [
                        t
                        for t in transcript_list
                        if not t.is_generated  # type: ignore
                    ]
                    if manual_transcripts:
                        # Use first available manual transcript
                        transcript = manual_transcripts[0]
                        logger.info(
                            f"Using manual transcript in {transcript.language_code} "  # type: ignore
                            f"for video {video_id}"
                        )
                except Exception:
                    pass

            # If still no transcript, try ASR (auto-generated)
            if not transcript:
                try:
                    generated_transcripts = [
                        t
                        for t in transcript_list
                        if t.is_generated  # type: ignore
                    ]
                    if generated_transcripts:
                        # Try to translate ASR to desired language
                        transcript = generated_transcripts[0].translate(language)  # type: ignore
                        logger.info(
                            f"Using translated ASR transcript in {language} "
                            f"for video {video_id}"
                        )
                except Exception as e:
                    logger.warning(f"Could not translate ASR transcript: {e}")
                    return None

            if not transcript:
                logger.warning(f"No transcripts available for video {video_id}")
                return None

            # Fetch transcript data
            transcript_data = transcript.fetch()  # type: ignore

            # Generate safe filename
            safe_title = self._sanitize_filename(video_title) if video_title else video_id

            results: dict[str, Path] = {}

            # Generate requested formats
            for fmt in formats:
                if fmt == "vtt":
                    vtt_path = self.output_dir / f"{safe_title}.{language}.vtt"
                    self._write_vtt(vtt_path, transcript_data)
                    results["vtt"] = vtt_path
                elif fmt == "srt":
                    srt_path = self.output_dir / f"{safe_title}.{language}.srt"
                    self._write_srt(srt_path, transcript_data)
                    results["srt"] = srt_path

            return results

        except (TranscriptsDisabledError, Exception) as e:  # type: ignore
            if "disabled" in str(e).lower() or isinstance(e, TranscriptsDisabledError):  # type: ignore
                logger.warning(f"Transcripts are disabled for video {video_id}")
            elif "not found" in str(e).lower() or isinstance(e, NoTranscriptFound):  # type: ignore
                logger.warning(f"No transcript found for video {video_id} in language {language}")
            else:
                logger.error(f"Error downloading transcript via API: {e}", exc_info=True)
            return None

    def _write_vtt(self, path: Path, transcript_data: list[dict[str, Any]]) -> None:
        """
        Write transcript data to WebVTT format.

        Args:
            path: Output file path
            transcript_data: List of transcript entries with 'text', 'start', 'duration'
        """
        with open(path, "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")

            for entry in transcript_data:
                start = entry.get("start", 0)
                duration = entry.get("duration", 0)
                end = start + duration
                text = entry.get("text", "").strip()

                # Format timestamps (HH:MM:SS.mmm)
                start_str = self._format_timestamp(start)
                end_str = self._format_timestamp(end)

                f.write(f"{start_str} --> {end_str}\n")
                f.write(f"{text}\n\n")

    def _write_srt(self, path: Path, transcript_data: list[dict[str, Any]]) -> None:
        """
        Write transcript data to SRT format.

        Args:
            path: Output file path
            transcript_data: List of transcript entries with 'text', 'start', 'duration'
        """
        with open(path, "w", encoding="utf-8") as f:
            for idx, entry in enumerate(transcript_data, 1):
                start = entry.get("start", 0)
                duration = entry.get("duration", 0)
                end = start + duration
                text = entry.get("text", "").strip()

                # Format timestamps (HH:MM:SS,mmm)
                start_str = self._format_timestamp_srt(start)
                end_str = self._format_timestamp_srt(end)

                f.write(f"{idx}\n")
                f.write(f"{start_str} --> {end_str}\n")
                f.write(f"{text}\n\n")

    def _format_timestamp(self, seconds: float) -> str:
        """
        Format seconds to WebVTT timestamp (HH:MM:SS.mmm).

        Args:
            seconds: Time in seconds

        Returns:
            Formatted timestamp string
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)

        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

    def _format_timestamp_srt(self, seconds: float) -> str:
        """
        Format seconds to SRT timestamp (HH:MM:SS,mmm).

        Args:
            seconds: Time in seconds

        Returns:
            Formatted timestamp string
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)

        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _convert_srt_to_vtt(
        self, srt_path: Path, video_id: str, video_title: str | None = None
    ) -> Path | None:
        """
        Convert SRT file to WebVTT format.

        Args:
            srt_path: Path to SRT file
            video_id: Video ID for filename
            video_title: Optional video title

        Returns:
            Path to VTT file, or None if conversion failed
        """
        try:
            safe_title = self._sanitize_filename(video_title) if video_title else video_id
            vtt_path = self.output_dir / f"{safe_title}.vtt"

            with open(srt_path, encoding="utf-8") as srt_file:
                content = srt_file.read()

            # Convert SRT to VTT
            # Replace comma with dot in timestamps
            vtt_content = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", content)

            # Add WebVTT header
            if not vtt_content.startswith("WEBVTT"):
                vtt_content = "WEBVTT\n\n" + vtt_content

            with open(vtt_path, "w", encoding="utf-8") as vtt_file:
                vtt_file.write(vtt_content)

            return vtt_path

        except Exception as e:
            logger.error(f"Failed to convert SRT to VTT: {e}")
            return None

    def _convert_vtt_to_srt(
        self, vtt_path: Path, video_id: str, video_title: str | None = None
    ) -> Path | None:
        """
        Convert WebVTT file to SRT format.

        Args:
            vtt_path: Path to VTT file
            video_id: Video ID for filename
            video_title: Optional video title

        Returns:
            Path to SRT file, or None if conversion failed
        """
        try:
            safe_title = self._sanitize_filename(video_title) if video_title else video_id
            srt_path = self.output_dir / f"{safe_title}.srt"

            with open(vtt_path, encoding="utf-8") as vtt_file:
                content = vtt_file.read()

            # Remove WebVTT header
            content = re.sub(r"^WEBVTT\s*\n", "", content, flags=re.MULTILINE)

            # Convert VTT to SRT
            # Replace dot with comma in timestamps
            srt_content = re.sub(r"(\d{2}:\d{2}:\d{2})\.(\d{3})", r"\1,\2", content)

            # Add sequence numbers (SRT format requires them)
            lines = srt_content.split("\n")
            srt_lines: list[str] = []
            seq_num = 1
            i = 0

            while i < len(lines):
                line = lines[i].strip()
                if not line:
                    i += 1
                    continue

                # Check if this is a timestamp line
                if "-->" in line:
                    srt_lines.append(str(seq_num))
                    srt_lines.append(line)
                    seq_num += 1
                    i += 1
                    # Add text lines until empty line
                    while i < len(lines) and lines[i].strip():
                        srt_lines.append(lines[i])
                        i += 1
                    srt_lines.append("")  # Empty line after subtitle
                else:
                    i += 1

            with open(srt_path, "w", encoding="utf-8") as srt_file:
                srt_file.write("\n".join(srt_lines))

            return srt_path

        except Exception as e:
            logger.error(f"Failed to convert VTT to SRT: {e}")
            return None

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename to prevent path traversal and invalid characters.

        Args:
            filename: Original filename

        Returns:
            Sanitized filename safe for filesystem use
        """
        # Remove path separators and dangerous characters
        sanitized = re.sub(r"[^\w\-_\. ]", "_", filename)
        # Remove leading/trailing dots and spaces
        sanitized = sanitized.strip(". ")
        # Limit length
        if len(sanitized) > 200:
            sanitized = sanitized[:200]
        return sanitized
