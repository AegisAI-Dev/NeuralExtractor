"""Bounded PO Token provider interface and disabled-by-default diagnostics.

V3.0.5 intentionally does not bundle a third-party provider.  Keeping the
interface explicit prevents manual token handling and avoids presenting PO
Token support as a substitute for account authentication.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class PoTokenFailure(str, Enum):
    PROVIDER_MISSING = "provider_missing"
    PROVIDER_START_FAILED = "provider_start_failed"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_INVALID_RESPONSE = "provider_invalid_response"
    TOKEN_GENERATION_FAILED = "token_generation_failed"
    TOKEN_REJECTED = "token_rejected"
    UNSUPPORTED_TOKEN_CONTEXT = "unsupported_token_context"
    TOKEN_EXPIRED = "token_expired"
    AUTHENTICATION_STILL_REQUIRED = "authentication_still_required"


@dataclass(frozen=True, slots=True)
class PoTokenRequest:
    client: str
    context: str
    content_binding: str


@dataclass(frozen=True, slots=True)
class PoTokenResult:
    success: bool
    failure: PoTokenFailure | None
    diagnostic: str


@dataclass(frozen=True, slots=True)
class PoTokenProviderStatus:
    available: bool
    bundled: bool
    provider_id: str
    version: str
    diagnostic: str


class PoTokenProvider(Protocol):
    @property
    def status(self) -> PoTokenProviderStatus: ...

    def generate(self, request: PoTokenRequest) -> PoTokenResult: ...


class DisabledPoTokenProvider:
    """Safe placeholder used until a reviewed provider can be bundled."""

    @property
    def status(self) -> PoTokenProviderStatus:
        return PoTokenProviderStatus(
            available=False,
            bundled=False,
            provider_id="none",
            version="",
            diagnostic=(
                "PO Token provider unavailable: V3.0.5 does not bundle a provider. "
                "Manual PO Tokens are not accepted."
            ),
        )

    def generate(self, request: PoTokenRequest) -> PoTokenResult:
        del request
        return PoTokenResult(
            success=False,
            failure=PoTokenFailure.PROVIDER_MISSING,
            diagnostic="PO Token provider unavailable.",
        )


def get_po_token_provider() -> PoTokenProvider:
    """Return only the reviewed provider compiled into this build."""
    return DisabledPoTokenProvider()


__all__ = [
    "DisabledPoTokenProvider",
    "PoTokenFailure",
    "PoTokenProvider",
    "PoTokenProviderStatus",
    "PoTokenRequest",
    "PoTokenResult",
    "get_po_token_provider",
]
