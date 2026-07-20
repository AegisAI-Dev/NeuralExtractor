"""Bounded yt-dlp preflight for a managed-browser YouTube session."""

from __future__ import annotations

from pathlib import Path

from neural_extractor_v3.config import app_data_dir
from neural_extractor_v3.core.downloader import DownloadEngine, YtdlpRunError
from neural_extractor_v3.core.process_control import ProcessLimits
from neural_extractor_v3.core.youtube_connection import ManagedBrowser, VerificationResult
from neural_extractor_v3.core.youtube_errors import FailureCategory, classify_youtube_failure
from neural_extractor_v3.models import DownloadOptions, MediaMode, PlaylistMode


def verify_dedicated_youtube_profile(
    profile_path: Path,
    target_url: str,
    *,
    browser: ManagedBrowser | str = ManagedBrowser.FIREFOX,
) -> VerificationResult:
    """Verify session usability without downloading media."""
    selected_browser = ManagedBrowser(browser)
    options = DownloadOptions(
        output_dir=app_data_dir() / "youtube" / "verification-output",
        media_mode=MediaMode.VIDEO,
        playlist_mode=PlaylistMode.SINGLE,
        subtitles=False,
        auto_subtitles=False,
        thumbnail=False,
        embed_thumbnail=False,
        metadata_json=False,
        dedicated_browser=selected_browser.value,
        dedicated_browser_profile=profile_path,
        guided_youtube_auth=True,
        legacy_browser_fallback=False,
    )
    engine = DownloadEngine(
        options,
        process_record_label="youtube-verification",
        process_limits=ProcessLimits(
            inactivity_timeout=45,
            total_timeout=90,
            status_interval=5,
            termination_grace=3,
            force_kill_wait=3,
        ),
    )
    try:
        if selected_browser is ManagedBrowser.FIREFOX:
            result = engine.run_authentication_preflight(target_url, profile_path)
        else:
            result = engine.run_authentication_preflight(
                target_url,
                profile_path,
                selected_browser,
            )
    except YtdlpRunError as exc:
        if exc.category_hint == FailureCategory.NETWORK_INACTIVITY_TIMEOUT:
            return VerificationResult(False, "timeout", "Network verification timed out.")
        if exc.category_hint == FailureCategory.TOTAL_ATTEMPT_TIMEOUT:
            return VerificationResult(False, "timeout", "Network verification timed out.")
        if exc.category_hint == FailureCategory.DEDICATED_PROFILE_INVALID:
            return VerificationResult(False, "invalid", "Dedicated browser profile is invalid.")
        analysis = classify_youtube_failure(
            exc.diagnostic_text(),
            auth_kind="dedicated_browser",
            javascript_runtime_available=engine.js_runtime_status.found,
        )
        if analysis.category == FailureCategory.YOUTUBE_SESSION_EXPIRED:
            return VerificationResult(False, "expired", "YouTube rejected the session.")
        if analysis.category == FailureCategory.YOUTUBE_ACCESS_RESTRICTED:
            return VerificationResult(False, "access_restricted", analysis.user_message)
        if analysis.category == FailureCategory.PO_TOKEN_REQUIRED:
            return VerificationResult(
                False,
                "po_token_required",
                "PO Token provider unavailable for this verification context.",
            )
        if analysis.category in {
            FailureCategory.NETWORK_TRANSIENT,
            FailureCategory.NETWORK_INACTIVITY_TIMEOUT,
            FailureCategory.TOTAL_ATTEMPT_TIMEOUT,
        }:
            return VerificationResult(False, "timeout", "Network verification timed out.")
        if analysis.category == FailureCategory.BROWSER_COOKIE_DATABASE_LOCKED:
            return VerificationResult(False, "locked", "Managed browser profile data is locked.")
        if analysis.category == FailureCategory.BROWSER_COOKIE_DECRYPTION_FAILED:
            return VerificationResult(
                False,
                "cookie_decryption_failed",
                "Chrome session could not be read securely. Try the managed Firefox connection."
                if selected_browser is ManagedBrowser.CHROME
                else analysis.user_message,
            )
        if analysis.category == FailureCategory.BROWSER_COOKIE_EXTRACTION_FAILED:
            return VerificationResult(
                False,
                "cookie_extraction_unsupported",
                "Chrome session could not be read securely. Try the managed Firefox connection."
                if selected_browser is ManagedBrowser.CHROME
                else analysis.user_message,
            )
        return VerificationResult(False, "session_rejected", "YouTube rejected the session.")
    except (OSError, RuntimeError, ValueError):
        return VerificationResult(False, "invalid", "Dedicated browser profile is invalid.")

    diagnostic = result.diagnostic.casefold()
    analysis = classify_youtube_failure(
        result.diagnostic,
        auth_kind="dedicated_browser",
        javascript_runtime_available=engine.js_runtime_status.found,
    )
    if analysis.category == FailureCategory.YOUTUBE_SESSION_EXPIRED:
        return VerificationResult(False, "expired", "YouTube rejected the session.")
    if not result.metadata.get("id") and not result.metadata.get("title"):
        return VerificationResult(
            False,
            "invalid_response",
            "YouTube verification returned no usable metadata.",
        )
    warning = ""
    if "po token" in diagnostic or "pot token" in diagnostic:
        warning = "Session verified; a PO Token may still be required for some formats."
    return VerificationResult(True, "connected", "YouTube session verified.", warning)


__all__ = ["verify_dedicated_youtube_profile"]
