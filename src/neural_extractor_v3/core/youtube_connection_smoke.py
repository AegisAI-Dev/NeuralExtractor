"""Offline packaged smoke for the guided YouTube connection components."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from neural_extractor_v3.core.youtube_connection import (
    FirefoxDiscovery,
    VerificationResult,
    YouTubeConnectionManager,
    validate_dedicated_profile_path,
)


class _MemorySettings:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def value(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.values[key] = value

    def remove(self, key: str) -> None:
        self.values.pop(key, None)

    def sync(self) -> None:
        return None


class _FakeProcess:
    pid = 4545

    def __init__(self) -> None:
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


def run_offline_youtube_connection_smoke() -> dict[str, bool]:
    """Exercise safety, argv, state, renewal, and disconnect without network/browser use."""
    with tempfile.TemporaryDirectory(prefix="neural-extractor-youtube-smoke-") as temporary:
        root = Path(temporary)
        application_data = root / "LocalAppData" / "NeuralExtractorV3"
        firefox = root / "Mozilla Firefox" / "firefox.exe"
        firefox.parent.mkdir(parents=True)
        firefox.write_bytes(b"MZ\x00\x00")
        process = _FakeProcess()
        captured: dict[str, Any] = {}

        def popen(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return process

        settings = _MemorySettings()
        manager = YouTubeConnectionManager(
            settings,
            application_data=application_data,
            discovery=FirefoxDiscovery(
                registry_reader=lambda: [firefox],
                environ={},
                binary_validator=lambda _path: True,
            ),
            popen_factory=popen,
            identity_provider=lambda _pid: "packaged-smoke-identity",
        )
        profile = manager.create_profile()
        traversal_rejected = False
        try:
            validate_dedicated_profile_path(
                profile / ".." / "escape",
                application_data=application_data,
                require_exists=False,
            )
        except ValueError:
            traversal_rejected = True

        manager.launch("https://www.youtube.com/watch?v=offline&token=must-not-appear")
        command = list(captured["command"])
        launch_safe = (
            captured["kwargs"].get("shell") is False
            and command[1:4] == ["-no-remote", "-profile", str(profile)]
            and "must-not-appear" not in " ".join(command)
        )
        process.returncode = 0
        manager.refresh_browser_state()

        cookie_database = sqlite3.connect(profile / "cookies.sqlite")
        try:
            connection = cookie_database
            connection.execute("CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT)")
            connection.execute(
                "INSERT INTO moz_cookies VALUES (?, ?, ?)",
                (".youtube.com", "SAPISID", "never-log-this-cookie"),
            )
            connection.commit()
        finally:
            cookie_database.close()
        verified = manager.verify(
            lambda checked_profile, _url: VerificationResult(
                checked_profile == profile,
                "connected",
                "YouTube session verified.",
            ),
            "https://www.youtube.com/watch?v=offline",
        )
        manager.mark_expired("cookies are no longer valid")
        renewal_reused_profile = manager.create_profile() == profile
        disconnected = manager.disconnect()
        settings_private = "never-log-this-cookie" not in repr(settings.values)
        return {
            "profile_path_safe": profile.parent == application_data / "youtube",
            "path_traversal_rejected": traversal_rejected,
            "launch_arguments_safe": launch_safe,
            "authentication_state_machine": verified.success,
            "renewal_reused_profile": renewal_reused_profile,
            "disconnect_safe": disconnected.success and not profile.exists(),
            "settings_private": settings_private,
        }


__all__ = ["run_offline_youtube_connection_smoke"]
