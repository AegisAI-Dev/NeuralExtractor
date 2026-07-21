import pytest

from neural_extractor_v3.core.youtube_errors import (
    FailureCategory,
    classify_youtube_failure,
)


@pytest.mark.parametrize(
    ("message", "category"),
    [
        (
            "ERROR: Could not copy Chrome cookie database",
            FailureCategory.BROWSER_COOKIE_DATABASE_LOCKED,
        ),
        (
            "ERROR: Failed to decrypt cookies with Windows DPAPI",
            FailureCategory.BROWSER_COOKIE_DECRYPTION_FAILED,
        ),
        (
            "WARNING: This client requires a PO Token for video playback",
            FailureCategory.PO_TOKEN_REQUIRED,
        ),
        (
            "ERROR: Requested format is not available",
            FailureCategory.REQUESTED_FORMAT_UNAVAILABLE,
        ),
        (
            "WARNING: n challenge solving failed. Only images are available",
            FailureCategory.ONLY_IMAGE_FORMATS_AVAILABLE,
        ),
        (
            "ERROR: Sign in to confirm your age. Use --cookies",
            FailureCategory.AUTHENTICATION_REQUIRED,
        ),
    ],
)
def test_failure_categories_are_separate(message, category):
    analysis = classify_youtube_failure(message)

    assert analysis.category == category


def test_node_found_plus_http_403_is_not_missing_node():
    analysis = classify_youtube_failure(
        "ERROR: unable to download video data: HTTP Error 403: Forbidden",
        javascript_runtime_available=True,
    )

    assert analysis.category == FailureCategory.HTTP_403_MEDIA_REJECTED
    assert "runtime" not in analysis.user_message.lower()


def test_node_found_plus_format_unavailable_is_not_missing_node():
    analysis = classify_youtube_failure(
        "ERROR: Requested format is not available",
        javascript_runtime_available=True,
    )

    assert analysis.category == FailureCategory.REQUESTED_FORMAT_UNAVAILABLE
    assert "runtime" not in analysis.user_message.lower()


def test_generic_n_challenge_with_node_found_is_not_missing_node():
    analysis = classify_youtube_failure(
        "WARNING: n challenge solving failed",
        javascript_runtime_available=True,
    )

    assert analysis.category == FailureCategory.UNKNOWN
    assert "even though" in analysis.user_message


def test_genuine_missing_javascript_runtime_is_detected():
    analysis = classify_youtube_failure(
        "WARNING: No supported JavaScript runtime could be found",
        javascript_runtime_available=False,
    )

    assert analysis.category == FailureCategory.JAVASCRIPT_RUNTIME_UNAVAILABLE


def test_cookie_file_http_403_is_rejected_cookie_not_generic_auth_requirement():
    analysis = classify_youtube_failure(
        "ERROR: unable to download video data: HTTP Error 403: Forbidden",
        auth_kind="cookies_file",
    )

    assert analysis.category == FailureCategory.COOKIE_FILE_REJECTED


def test_generic_http_403_does_not_claim_authentication_is_required():
    analysis = classify_youtube_failure(
        "ERROR: unable to download video data: HTTP Error 403: Forbidden",
        auth_kind="none",
    )

    assert analysis.category == FailureCategory.HTTP_403_MEDIA_REJECTED
    assert not analysis.authentication_specific


def test_cp1252_unicode_transport_failure_has_specific_worker_category():
    analysis = classify_youtube_failure(
        "UnicodeEncodeError: 'charmap' codec can't encode character '\\uff5c' "
        "using encodings/cp1252.py",
    )

    assert analysis.category == FailureCategory.WORKER_PROTOCOL_ERROR
    assert analysis.category != FailureCategory.UNKNOWN
