from pathlib import Path

from neural_extractor_v3.core.auth import (
    BROWSER_FALLBACK_ORDER,
    BrowserCookieSource,
    clean_authentication_error,
    clean_browser_cookie_extraction_error,
    clean_live_event_ended_error,
    inspect_cookie_file,
    is_authentication_error,
    is_browser_cookie_extraction_error,
    is_live_event_ended_error,
    resolve_auth_strategies,
)


def _write_cookie_file(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_cookie_file_is_priority_when_valid(tmp_path):
    cookie_file = _write_cookie_file(
        tmp_path / "cookies.txt",
        "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tFALSE\t0\tSID\tredacted\n",
    )
    browser = BrowserCookieSource("chrome", "Chrome", tmp_path / "Chrome")
    resolution = resolve_auth_strategies(cookie_file, browser_detector=lambda: [browser])

    assert [strategy.kind for strategy in resolution.strategies] == ["cookies_file", "browser"]
    assert resolution.strategies[0].ydl_options["cookiefile"] == str(cookie_file)
    assert resolution.strategies[1].ydl_options["cookiesfrombrowser"] == ("chrome",)


def test_browser_cookies_are_used_when_cookie_file_missing(tmp_path):
    browser = BrowserCookieSource("edge", "Edge", tmp_path / "Edge")
    resolution = resolve_auth_strategies(None, browser_detector=lambda: [browser])

    assert [strategy.kind for strategy in resolution.strategies] == ["browser"]
    assert resolution.strategies[0].ydl_options["cookiesfrombrowser"] == ("edge",)
    assert any("cookies.txt not loaded" in message for message in resolution.messages)


def test_invalid_cookie_file_falls_back_to_browser(tmp_path):
    cookie_file = _write_cookie_file(tmp_path / "cookies.txt", "# header only\n")
    browser = BrowserCookieSource("firefox", "Firefox", tmp_path / "Firefox")
    resolution = resolve_auth_strategies(cookie_file, browser_detector=lambda: [browser])

    assert [strategy.kind for strategy in resolution.strategies] == ["browser"]
    assert "invalid" in resolution.messages[0]


def test_no_auth_strategy_when_no_cookie_or_browser():
    resolution = resolve_auth_strategies(None, browser_detector=lambda: [])

    assert [strategy.kind for strategy in resolution.strategies] == ["none"]
    assert not resolution.strategies[0].attempted_auth
    assert any("browser cookies unavailable" in message for message in resolution.messages)


def test_cookie_file_inspection_never_requires_secret_values(tmp_path):
    cookie_file = _write_cookie_file(
        tmp_path / "cookies.txt",
        ".google.com\tTRUE\t/\tTRUE\t0\tSAPISID\tredacted-secret-value\n",
    )

    status = inspect_cookie_file(cookie_file)

    assert status.valid
    assert "redacted-secret-value" not in status.reason


def test_authentication_error_detection_and_clean_messages():
    assert is_authentication_error("Sign in to confirm you're not a bot. Use --cookies")
    assert clean_authentication_error(True) == (
        "Cookies appear expired or invalid. Please export fresh cookies from your browser."
    )
    assert "Authentication unavailable" in clean_authentication_error(False)


def test_browser_fallback_order_and_multiple_strategies(tmp_path):
    sources = [
        BrowserCookieSource("chrome", "Chrome", tmp_path / "Chrome"),
        BrowserCookieSource("edge", "Edge", tmp_path / "Edge"),
        BrowserCookieSource("brave", "Brave", tmp_path / "Brave"),
        BrowserCookieSource("firefox", "Firefox", tmp_path / "Firefox"),
    ]

    resolution = resolve_auth_strategies(None, browser_detector=lambda: sources)

    assert tuple(strategy.ydl_options["cookiesfrombrowser"][0] for strategy in resolution.strategies) == (
        "chrome",
        "edge",
        "brave",
        "firefox",
    )
    assert tuple(source.browser for source in resolution.browser_sources) == BROWSER_FALLBACK_ORDER


def test_browser_cookie_extraction_error_is_not_auth_error():
    error = "ERROR: Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues"

    assert is_browser_cookie_extraction_error(error)
    assert not is_authentication_error(error)
    assert clean_browser_cookie_extraction_error() == (
        "Browser cookie extraction failed. Close your browser or export cookies.txt manually."
    )


def test_live_event_ended_is_not_auth_error():
    error = "ERROR: [youtube] abc123: This live event has ended."

    assert is_live_event_ended_error(error)
    assert not is_authentication_error(error)
    assert clean_live_event_ended_error() == (
        "This live event has ended and is not currently downloadable."
    )
