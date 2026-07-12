"""Isolated yt-dlp worker protocol used by each Neural Extractor attempt."""

from __future__ import annotations

import contextlib
import json
import sys
import traceback
from collections.abc import Mapping
from typing import Any, TextIO

import yt_dlp

PROTOCOL_PREFIX = "NEURAL_EXTRACTOR_EVENT "


def _stdio_stream(fd: int, fallback: TextIO | None, mode: str) -> TextIO:
    """Use redirected OS pipes even in a PyInstaller windowed executable."""
    if fallback is not None:
        return fallback
    return open(fd, mode, encoding="utf-8", errors="replace", buffering=1, closefd=False)


_PROTOCOL_STREAM: TextIO | None = sys.stdout


def _protocol_stream() -> TextIO:
    global _PROTOCOL_STREAM
    if _PROTOCOL_STREAM is None:
        _PROTOCOL_STREAM = _stdio_stream(1, None, "w")
    return _PROTOCOL_STREAM


def _emit(kind: str, **payload: Any) -> None:
    document = json.dumps({"kind": kind, **payload}, ensure_ascii=False, default=str)
    stream = _protocol_stream()
    stream.write(f"{PROTOCOL_PREFIX}{document}\n")
    stream.flush()


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
                    _emit("metadata", formats=_summarize_formats(info))
                else:
                    if not playlist:
                        _emit("phase", phase="preflight", message="Preparing YouTube metadata")
                        info = ydl.extract_info(url, download=False)
                        _emit("metadata", formats=_summarize_formats(info))
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
    return run_worker(request)


if __name__ == "__main__":
    raise SystemExit(main())
