"""Isolated yt-dlp worker protocol used by each Neural Extractor attempt."""

from __future__ import annotations

import contextlib
import json
import threading
import traceback
from collections.abc import Mapping
from typing import Any, BinaryIO, TextIO

import yt_dlp

PROTOCOL_PREFIX = "NEURAL_EXTRACTOR_EVENT "
PROTOCOL_ENCODING = "utf-8"
PROTOCOL_SMOKE_TITLE = "Artist ｜ Greatest Hits ❤️ Nederlandse Muziek — 夜の名曲"


def _stdio_stream(fd: int, fallback: TextIO | None, mode: str) -> TextIO:
    """Use redirected OS pipes even in a PyInstaller windowed executable."""
    if fallback is not None:
        return fallback
    return open(
        fd,
        mode,
        encoding=PROTOCOL_ENCODING,
        errors="replace",
        buffering=1,
        closefd=False,
    )


_PROTOCOL_STREAM: BinaryIO | None = None
_PROTOCOL_LOCK = threading.Lock()


def _protocol_stream() -> BinaryIO:
    global _PROTOCOL_STREAM
    if _PROTOCOL_STREAM is None:
        # The worker is always launched with fd 1 connected to a parent-owned
        # binary pipe. Bypass sys.stdout so a Windows CP1252 TextIOWrapper can
        # never encode or reject machine-protocol characters.
        _PROTOCOL_STREAM = open(1, "wb", buffering=0, closefd=False)
    return _PROTOCOL_STREAM


def _emit(kind: str, **payload: Any) -> None:
    document = json.dumps({"kind": kind, **payload}, ensure_ascii=False, default=str)
    frame = f"{PROTOCOL_PREFIX}{document}\n".encode(PROTOCOL_ENCODING)
    with _PROTOCOL_LOCK:
        stream = _protocol_stream()
        remaining = memoryview(frame)
        while remaining:
            written = stream.write(remaining)
            if written is None or written <= 0:
                raise OSError("Could not write the complete worker protocol frame")
            remaining = remaining[written:]
        stream.flush()


def run_protocol_smoke() -> int:
    """Emit fixed offline Unicode frames for source and packaged validation."""
    payload = {
        "title": PROTOCOL_SMOKE_TITLE,
        "subtitle_destination": r"C:\Muziek\Nederlandse ondertitels｜夜の名曲.srt",
        "emoji": "❤️ 🚀",
        "cjk": "日本語 中文 한국어",
        "cyrillic": "Русская музыка",
        "arabic": "الموسيقى العربية",
        "combining": "Cafe\u0301",
        "long_windows_path": "C:\\Unicode\\" + ("非常に長いフォルダー\\" * 28) + "video.mp4",
    }
    for sequence in range(2):
        _emit("protocol_smoke", sequence=sequence, **payload)
    return 0


class ProtocolLogger:
    """Forward yt-dlp logger records to the parent without protocol ambiguity."""

    def debug(self, message: str) -> None:
        if message:
            _emit("log", stream="stdout", message=str(message))

    def warning(self, message: str) -> None:
        if message:
            _emit("log", stream="stderr", message=f"WARNING: {message}")

    def error(self, message: str) -> None:
        if message:
            _emit("log", stream="stderr", message=str(message))


class ProtocolTextStream:
    """Convert incidental stdout/stderr writes into complete protocol log lines."""

    def __init__(self, stream: str) -> None:
        self.stream = stream
        self._buffer = ""

    def write(self, value: str) -> int:
        self._buffer += str(value)
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                _emit("log", stream=self.stream, message=line.rstrip())
        return len(value)

    def flush(self) -> None:
        if self._buffer.strip():
            _emit("log", stream=self.stream, message=self._buffer.rstrip())
        self._buffer = ""


def _progress_hook(data: Mapping[str, Any]) -> None:
    info = data.get("info_dict") or {}
    if not isinstance(info, Mapping):
        info = {}
    _emit(
        "progress",
        data={
            "status": data.get("status", "working"),
            "filename": data.get("filename") or info.get("filepath") or "",
            "downloaded_bytes": data.get("downloaded_bytes") or 0,
            "total_bytes": data.get("total_bytes") or 0,
            "total_bytes_estimate": data.get("total_bytes_estimate") or 0,
            "speed": data.get("speed"),
            "eta": data.get("eta"),
            "info_dict": {
                "title": info.get("title") or "",
                "filepath": info.get("filepath") or "",
                "playlist_index": info.get("playlist_index"),
                "n_entries": info.get("n_entries"),
                "playlist_count": info.get("playlist_count"),
            },
        },
    )


def _summarize_formats(info: Any) -> list[dict[str, Any]]:
    if not isinstance(info, Mapping):
        return []
    formats = info.get("formats")
    if not isinstance(formats, list):
        return []
    summarized: list[dict[str, Any]] = []
    for item in formats:
        if not isinstance(item, Mapping) or not item.get("format_id"):
            continue
        summarized.append(
            {
                "format_id": str(item.get("format_id")),
                "ext": str(item.get("ext") or ""),
                "vcodec": str(item.get("vcodec") or "none"),
                "acodec": str(item.get("acodec") or "none"),
                "height": item.get("height"),
                "tbr": item.get("tbr"),
                "abr": item.get("abr"),
                "protocol": str(item.get("protocol") or ""),
            }
        )
    return summarized


def _metadata_event(info: Any) -> dict[str, Any]:
    if not isinstance(info, Mapping):
        return {"formats": []}
    return {
        "formats": _summarize_formats(info),
        "id": str(info.get("id") or ""),
        "title": str(info.get("title") or ""),
        "availability": str(info.get("availability") or ""),
        "live_status": str(info.get("live_status") or ""),
    }


def run_worker(request: Mapping[str, Any]) -> int:
    url = str(request.get("url") or "")
    raw_options = request.get("options")
    if not url or not isinstance(raw_options, Mapping):
        _emit("error", phase="startup", message="Invalid internal yt-dlp worker request")
        return 2

    mode = str(request.get("mode") or "download")
    playlist = bool(request.get("playlist"))
    options = dict(raw_options)
    options["logger"] = ProtocolLogger()
    options["progress_hooks"] = [_progress_hook]
    if isinstance(options.get("cookiesfrombrowser"), list):
        options["cookiesfrombrowser"] = tuple(options["cookiesfrombrowser"])

    if mode == "discover":
        options.pop("format", None)
        options.pop("postprocessors", None)
        options["skip_download"] = True
        options["simulate"] = True
        options["ignore_no_formats_error"] = True

    redirected_out = ProtocolTextStream("stdout")
    redirected_err = ProtocolTextStream("stderr")
    phase = "discovery" if mode == "discover" else "preflight"

    try:
        with contextlib.redirect_stdout(redirected_out), contextlib.redirect_stderr(redirected_err):
            with yt_dlp.YoutubeDL(options) as ydl:
                if mode == "discover":
                    _emit("phase", phase="discovery", message="Inspecting available YouTube formats")
                    info = ydl.extract_info(url, download=False)
                    _emit("metadata", **_metadata_event(info))
                else:
                    if not playlist:
                        _emit("phase", phase="preflight", message="Preparing YouTube metadata")
                        info = ydl.extract_info(url, download=False)
                        _emit("metadata", **_metadata_event(info))
                    phase = "download"
                    _emit(
                        "phase",
                        phase="download",
                        message=str(request.get("activity_label") or "Downloading media"),
                    )
                    retcode = ydl.download([url])
                    if retcode:
                        _emit("error", phase=phase, message=f"yt-dlp returned exit code {retcode}")
                        return int(retcode)
    except BaseException as exc:
        _emit(
            "error",
            phase=phase,
            message=str(exc),
            traceback="".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ).strip(),
        )
        return 1
    finally:
        redirected_out.flush()
        redirected_err.flush()

    _emit("result", success=True)
    return 0


def main() -> int:
    try:
        # PyInstaller's windowed bootloader may install a non-None dummy stdin.
        # The parent always supplies an OS pipe, so read fd 0 directly here.
        input_stream = _stdio_stream(0, None, "r")
        request = json.loads(input_stream.read())
    except (OSError, json.JSONDecodeError) as exc:
        _emit("error", phase="startup", message=f"Invalid internal request: {exc}")
        return 2
    if not isinstance(request, Mapping):
        _emit("error", phase="startup", message="Internal request must be a JSON object")
        return 2
    if request.get("mode") == "protocol_smoke":
        return run_protocol_smoke()
    return run_worker(request)


if __name__ == "__main__":
    raise SystemExit(main())
