"""Authentication option resolution for yt-dlp."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_BROWSER_NAMES = {
    "brave": "Brave",
    "chrome": "Chrome",
    "edge": "Edge",
    "firefox": "Firefox",
}

AUTH_COOKIE_DOMAINS = (
    "youtube.com",
    ".youtube.com",
    "google.com",
    ".google.com",
    "accounts.google.com",
)


@dataclass(frozen=True, slots=True)
class CookieFileStatus:
    path: Path | None
    valid: bool
    reason: str

    @property
    def display_name(self) -> str:
        if not self.path:
            return "cookies.txt"
        return self.path.name or "cookies.txt"


@dataclass(frozen=True, slots=True)
class BrowserCookieSource:
    browser: str
    display_name: str
    profile_path: Path


@dataclass(frozen=True, slots=True)
class AuthStrategy:
    kind: str
    display_name: str
    ydl_options: dict[str, Any]
    attempted_auth: bool = False

    @property
    def is_cookie_file(self) -> bool:
        return self.kind == "cookies_file"

    @property
    def is_browser(self) -> bool:
        return self.kind == "browser"


@dataclass(frozen=True, slots=True)
class AuthResolution:
    strategies: list[AuthStrategy]
    messages: list[str]
    cookie_file_status: CookieFileStatus
    browser_source: BrowserCookieSource | None


BrowserDetector = Callable[[], BrowserCookieSource | None]


def inspect_cookie_file(cookie_file: Path | None) -> CookieFileStatus:
    """Validate whether a cookies.txt file looks usable for YouTube auth."""
    if not cookie_file:
        return CookieFileStatus(None, False, "cookies.txt not loaded")

    path = Path(cookie_file).expanduser()
    if not path.exists():
        return CookieFileStatus(path, False, "cookies.txt not found")
    if not path.is_file():
        return CookieFileStatus(path, False, "cookies.txt path is not a file")
    try:
        if path.stat().st_size <= 0:
            return CookieFileStatus(path, False, "cookies.txt is empty")
    except OSError:
        return CookieFileStatus(path, False, "cookies.txt cannot be inspected")

    try:
        has_cookie_rows = False
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                has_cookie_rows = True
                lowered = stripped.lower()
                if any(domain in lowered for domain in AUTH_COOKIE_DOMAINS):
                    return CookieFileStatus(path, True, "cookies.txt contains YouTube/Google cookies")
    except OSError:
        return CookieFileStatus(path, False, "cookies.txt cannot be read")

    if not has_cookie_rows:
        return CookieFileStatus(path, False, "cookies.txt contains no cookie rows")
    return CookieFileStatus(path, False, "cookies.txt contains no YouTube/Google cookie rows")


def detect_browser_cookie_source() -> BrowserCookieSource | None:
    """Return the first supported browser profile found on this machine."""
    candidates: list[tuple[str, Path]]
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", "")).expanduser()
        roaming = Path(os.environ.get("APPDATA", "")).expanduser()
        candidates = [
            ("chrome", local / "Google" / "Chrome" / "User Data"),
            ("edge", local / "Microsoft" / "Edge" / "User Data"),
            ("firefox", roaming / "Mozilla" / "Firefox" / "Profiles"),
            ("brave", local / "BraveSoftware" / "Brave-Browser" / "User Data"),
        ]
    elif sys.platform == "darwin":
        support = Path.home() / "Library" / "Application Support"
        candidates = [
            ("chrome", support / "Google" / "Chrome"),
            ("edge", support / "Microsoft Edge"),
            ("firefox", support / "Firefox" / "Profiles"),
            ("brave", support / "BraveSoftware" / "Brave-Browser"),
        ]
    else:
        config = Path.home() / ".config"
        candidates = [
            ("chrome", config / "google-chrome"),
            ("edge", config / "microsoft-edge"),
            ("firefox", Path.home() / ".mozilla" / "firefox"),
            ("brave", config / "BraveSoftware" / "Brave-Browser"),
        ]

    for browser, profile_path in candidates:
        if profile_path.exists():
            return BrowserCookieSource(
                browser=browser,
                display_name=SUPPORTED_BROWSER_NAMES[browser],
                profile_path=profile_path,
            )
    return None


def resolve_auth_strategies(
    cookie_file: Path | None,
    browser_detector: BrowserDetector = detect_browser_cookie_source,
) -> AuthResolution:
    """Build ordered auth strategies for yt-dlp.

    cookies.txt is always first when it looks usable. Browser cookies are a fallback.
    A final unauthenticated strategy remains so public videos still work.
    """
    messages: list[str] = []
    strategies: list[AuthStrategy] = []

    cookie_status = inspect_cookie_file(cookie_file)
    if cookie_status.valid and cookie_status.path:
        messages.append(f"cookies.txt found: {cookie_status.display_name}")
        strategies.append(
            AuthStrategy(
                kind="cookies_file",
                display_name="cookies.txt",
                attempted_auth=True,
                ydl_options={
                    "cookiefile": str(cookie_status.path),
                    "extractor_args": {"youtube": {"player_client": ["default"]}},
                },
            )
        )
    elif cookie_file:
        messages.append(f"cookies.txt invalid: {cookie_status.display_name} ({cookie_status.reason})")
    else:
        messages.append("cookies.txt not loaded")

    browser_source = browser_detector()
    if browser_source:
        if strategies:
            messages.append(f"browser cookie fallback available: {browser_source.display_name}")
        else:
            messages.append(f"browser cookies available: {browser_source.display_name}")
        strategies.append(
            AuthStrategy(
                kind="browser",
                display_name=browser_source.display_name,
                attempted_auth=True,
                ydl_options={
                    "cookiesfrombrowser": (browser_source.browser,),
                    "extractor_args": {"youtube": {"player_client": ["default"]}},
                },
            )
        )
    else:
        messages.append("browser cookies unavailable: no Chrome, Edge, Firefox, or Brave profile found")

    if not strategies:
        strategies.append(
            AuthStrategy(
                kind="none",
                display_name="no authentication",
                attempted_auth=False,
                ydl_options={},
            )
        )

    return AuthResolution(
        strategies=strategies,
        messages=messages,
        cookie_file_status=cookie_status,
        browser_source=browser_source,
    )


def is_authentication_error(error_text: str) -> bool:
    """Return True when a yt-dlp error is likely auth/cookie related."""
    lowered = error_text.lower()
    patterns = (
        "sign in to confirm",
        "not a bot",
        "use --cookies",
        "cookies-from-browser",
        "cookies from browser",
        "cookie file",
        "login required",
        "private video",
        "members-only",
        "members only",
        "confirm your age",
        "age-restricted",
        "authentication",
    )
    return any(pattern in lowered for pattern in patterns)


def clean_authentication_error(auth_was_attempted: bool) -> str:
    if auth_was_attempted:
        return "Cookies appear expired or invalid. Please export fresh cookies from your browser."
    return (
        "Authentication unavailable. Add a fresh cookies.txt file or sign in with "
        "Chrome, Edge, Firefox, or Brave so browser cookies can be used."
    )
