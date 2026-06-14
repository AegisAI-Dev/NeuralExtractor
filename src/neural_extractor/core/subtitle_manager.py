"""Subtitle Manager for Neural Extractor v2.

Handles Dutch subtitle download with three fallback levels:
1. Native NL-track from YouTube
2. YouTube-Transcript-API fallback
3. Local Whisper transcription
"""

import json
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import timedelta

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

from neural_extractor.logger import logger

# Configure module logger
subtitle_logger = logging.getLogger(__name__)


class SubtitleSignalEmitter:
    """Emitter for subtitle-related signals."""
    
    def __init__(self) -> None:
        """Initialize signal emitter."""
        self.status_callback = None
        self.progress_callback = None
        self.complete_callback = None
        self.error_callback = None
    
    def set_status_callback(self, callback) -> None:
        """Set status callback."""
        self.status_callback = callback
    
    def set_progress_callback(self, callback) -> None:
        """Set progress callback."""
        self.progress_callback = callback
    
    def set_complete_callback(self, callback) -> None:
        """Set complete callback."""
        self.complete_callback = callback
    
    def set_error_callback(self, callback) -> None:
        """Set error callback."""
        self.error_callback = callback
    
    def emit_status(self, status: str) -> None:
        """Emit status signal."""
        if self.status_callback:
            self.status_callback(status)
    
    def emit_progress(self, progress: float) -> None:
        """Emit progress signal."""
        if self.progress_callback:
            self.progress_callback(progress)
    
    def emit_complete(self, result: Optional[Path]) -> None:
        """Emit complete signal."""
        if self.complete_callback:
            self.complete_callback(result)
    
    def emit_error(self, error: str) -> None:
        """Emit error signal."""
        if self.error_callback:
            self.error_callback(error)


class SubtitleManager:
    """Manager for Dutch subtitle download with fallback logic."""
    
    def __init__(self, output_dir: Optional[Path] = None, cookie_file: Optional[Path] = None) -> None:
        """Initialize subtitle manager.
        
        Args:
            output_dir: Directory to save subtitle files. If None, uses current directory.
            cookie_file: Path to cookies.txt for YouTube authentication.
        """
        self.output_dir = output_dir or Path.cwd()
        self.cookie_file = cookie_file
        self.status_callback = None
        self.signal_emitter = SubtitleSignalEmitter()
        self.whisper_thread = None
        
    def set_status_callback(self, callback) -> None:
        """Set callback for status updates.
        
        Args:
            callback: Function to call with status updates (str)
        """
        self.status_callback = callback
        
    def _update_status(self, status: str) -> None:
        """Update status via callback if set.
        
        Args:
            status: Status message
        """
        if self.status_callback:
            self.status_callback(status)
        subtitle_logger.info(status)
    
    def get_subtitles(self, video_url: str, video_title: str, lang: str = "nl") -> Optional[Path]:
        """Get subtitles using three-level fallback.
        
        Args:
            video_url: YouTube video URL
            video_title: Video title for filename
            lang: Language code for subtitles (default: 'nl')
            
        Returns:
            Path to .srt file if successful, None otherwise
        """
        self._update_status(f"Zoek naar {lang} ondertitels...")
        
        # Level 1: Try native track
        srt_path = self._try_native_track(video_url, video_title, lang)
        if srt_path:
            self._update_status(f"Native {lang}-track gevonden op YouTube")
            return srt_path
        
        # Level 2: Try YouTube-Transcript-API
        self._update_status("Native track niet gevonden, probeer API...")
        srt_path = self._try_transcript_api(video_url, video_title, lang)
        if srt_path:
            self._update_status(f"Auto-vertaling naar {lang} via API gelukt")
            return srt_path
        
        # Level 3: Try local Whisper transcription
        self._update_status("API mislukt, start lokale transcriptie...")
        srt_path = self._try_whisper_transcription(video_url, video_title, lang)
        if srt_path:
            self._update_status("Eigen transcriptie gelukt")
            return srt_path
        
        self._update_status(f"Kon geen {lang}-ondertitels genereren")
        return None
    
    def _try_native_track(self, video_url: str, video_title: str, lang: str) -> Optional[Path]:
        """Try to download native subtitle track from YouTube.
        
        Args:
            video_url: YouTube video URL
            video_title: Video title for filename
            
        Returns:
            Path to .srt file if successful, None otherwise
        """
        try:
            ydl_opts = {
                'writesubtitles': True,
                'subtitleslangs': [lang],
                'subtitlesformat': 'srt',
                'skip_download': True,
                'quiet': True,
                'no_warnings': True,
            }
            if self.cookie_file and self.cookie_file.exists():
                ydl_opts['cookiefile'] = str(self.cookie_file)
                ydl_opts['extractor_args'] = {'youtube': {'player_client': ['default']}}
            else:
                ydl_opts['extractor_args'] = {'youtube': {'player_client': ['mweb']}}
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract video info to check for subtitles
                info = ydl.extract_info(video_url, download=False)
                
                # Check if subtitles are available
                subtitles = info.get('subtitles', {})
                if lang in subtitles:
                    # Download the subtitle
                    ydl_opts['outtmpl'] = str(self.output_dir / f"{video_title}.%(ext)s")
                    ydl_opts['writesubtitles'] = True
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl_download:
                        ydl_download.download([video_url])
                    
                    # Rename
                    srt_file = self.output_dir / f"{video_title}.{lang}.srt"
                    original_srt = self.output_dir / f"{video_title}.{lang}.srt"
                    
                    if original_srt.exists():
                        return original_srt
                    
        except Exception as e:
            subtitle_logger.warning(f"Native NL-track failed: {e}")
        
        return None
    
    def _try_transcript_api(self, video_url: str, video_title: str, lang: str) -> Optional[Path]:
        """Try to get subtitles via YouTube-Transcript-API.
        
        Args:
            video_url: YouTube video URL
            video_title: Video title for filename
            lang: Target language code
            
        Returns:
            Path to .srt file if successful, None otherwise
        """
        try:
            # Extract video ID from URL
            video_id = self._extract_video_id(video_url)
            if not video_id:
                return None
            
            # Try to get transcript with auto-translation
            kwargs = {}
            if self.cookie_file and self.cookie_file.exists():
                kwargs['cookies'] = str(self.cookie_file)

            transcript = YouTubeTranscriptApi.get_transcript(
                video_id, 
                languages=[lang, 'auto'],
                **kwargs
            )
            
            # Convert transcript to SRT format
            srt_content = self._transcript_to_srt(transcript)
            
            # Save to file
            srt_path = self.output_dir / f"{video_title}.{lang}.srt"
            with open(srt_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            return srt_path
            
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            subtitle_logger.warning(f"Transcript API failed: {e}")
        except Exception as e:
            subtitle_logger.warning(f"Transcript API error: {e}")
        
        return None
    
    def _try_whisper_transcription(self, video_url: str, video_title: str, lang: str) -> Optional[Path]:
        """Try to transcribe audio using Whisper in a separate thread.
        
        Args:
            video_url: YouTube video URL
            video_title: Video title for filename
            lang: Target language code
            
        Returns:
            Path to .srt file if successful, None otherwise
        """
        try:
            # Check if whisper is available
            import whisper
        except ImportError:
            subtitle_logger.warning("Whisper not installed, skipping transcription")
            self.signal_emitter.emit_status("Whisper niet geïnstalleerd")
            return None
        
        # Run Whisper synchronously (we are already in a background thread)
        return self._run_whisper_transcription(video_url, video_title, lang)
    
    def _run_whisper_transcription(self, video_url: str, video_title: str, lang: str) -> Optional[Path]:
        """Run Whisper transcription in background thread.
        
        Args:
            video_url: YouTube video URL
            video_title: Video title for filename
            lang: Target language code
        """
        try:
            self.signal_emitter.emit_status("Audio downloaden voor transcriptie...")
            
            # Download audio
            audio_path = self._download_audio(video_url, video_title)
            if not audio_path:
                self.signal_emitter.emit_error("Audio download mislukt")
                return None
            
            self.signal_emitter.emit_status("Whisper transcriptie uitvoeren...")
            
            # Load Whisper model
            import whisper
            model = whisper.load_model("base")
            
            # Transcribe with target language
            result = model.transcribe(
                str(audio_path),
                language=lang,
                task="transcribe"
            )
            
            # Convert to SRT
            srt_content = self._whisper_to_srt(result['segments'])
            
            # Save to file
            srt_path = self.output_dir / f"{video_title}.{lang}.srt"
            with open(srt_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            # Clean up audio file
            audio_path.unlink()
            
            self.signal_emitter.emit_status("Transcriptie voltooid")
            self.signal_emitter.emit_complete(srt_path)
            return srt_path
            
        except Exception as e:
            subtitle_logger.warning(f"Whisper transcription failed: {e}")
            self.signal_emitter.emit_error(f"Transcriptie mislukt: {e}")
            return None
    
    def _download_audio(self, video_url: str, video_title: str) -> Optional[Path]:
        """Download audio from YouTube for transcription.
        
        Args:
            video_url: YouTube video URL
            video_title: Video title for filename
            
        Returns:
            Path to audio file if successful, None otherwise
        """
        try:
            audio_path = self.output_dir / f"{video_title}.wav"
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '192',
                }],
                'outtmpl': str(audio_path.with_suffix('')),
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            if audio_path.exists():
                return audio_path
            
        except Exception as e:
            subtitle_logger.warning(f"Audio download failed: {e}")
        
        return None
    
    def _extract_video_id(self, video_url: str) -> Optional[str]:
        """Extract video ID from YouTube URL.
        
        Args:
            video_url: YouTube video URL
            
        Returns:
            Video ID if found, None otherwise
        """
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(video_url, download=False)
                return info.get('id')
        except Exception:
            return None
    
    def _transcript_to_srt(self, transcript: list) -> str:
        """Convert YouTube transcript to SRT format.
        
        Args:
            transcript: List of transcript segments
            
        Returns:
            SRT formatted string
        """
        srt_lines = []
        
        for i, segment in enumerate(transcript, 1):
            start_time = self._seconds_to_srt_time(segment['start'])
            end_time = self._seconds_to_srt_time(segment['start'] + segment['duration'])
            text = segment['text'].strip()
            
            srt_lines.append(f"{i}")
            srt_lines.append(f"{start_time} --> {end_time}")
            srt_lines.append(text)
            srt_lines.append("")
        
        return "\n".join(srt_lines)
    
    def _whisper_to_srt(self, segments: list) -> str:
        """Convert Whisper segments to SRT format.
        
        Args:
            segments: List of Whisper segments
            
        Returns:
            SRT formatted string
        """
        srt_lines = []
        
        for i, segment in enumerate(segments, 1):
            start_time = self._seconds_to_srt_time(segment['start'])
            end_time = self._seconds_to_srt_time(segment['end'])
            text = segment['text'].strip()
            
            srt_lines.append(f"{i}")
            srt_lines.append(f"{start_time} --> {end_time}")
            srt_lines.append(text)
            srt_lines.append("")
        
        return "\n".join(srt_lines)
    
    def _seconds_to_srt_time(self, seconds: float) -> str:
        """Convert seconds to SRT time format (HH:MM:SS,mmm).
        
        Args:
            seconds: Time in seconds
            
        Returns:
            SRT formatted time string
        """
        td = timedelta(seconds=seconds)
        hours, remainder = divmod(td.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        milliseconds = td.microseconds // 1000
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
