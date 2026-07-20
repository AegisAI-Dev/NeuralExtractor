from neural_extractor_v3.core.pot_provider import (
    PoTokenFailure,
    PoTokenRequest,
    get_po_token_provider,
)


def test_po_token_provider_interface_reports_unavailable_without_token_material():
    provider = get_po_token_provider()
    status = provider.status
    assert not status.available
    assert not status.bundled
    assert status.provider_id == "none"
    assert "unavailable" in status.diagnostic.lower()
    assert "manual po tokens are not accepted" in status.diagnostic.lower()

    result = provider.generate(PoTokenRequest("mweb", "gvs", "video-id"))
    assert not result.success
    assert result.failure == PoTokenFailure.PROVIDER_MISSING
    assert not hasattr(result, "token")
