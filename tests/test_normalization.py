from __future__ import annotations

import base64

import httpx

from scanner.libs.connectors.ebay import (
    EbayConnector,
    EbayOAuthTokenProvider,
    StubEbayBrowseProvider,
)
from scanner.libs.utils.config import EbaySettings


def test_ebay_item_summary_normalizes_to_raw_listing_event(fixture_loader) -> None:
    item_summary = fixture_loader("ebay_item_summary.json")
    connector = EbayConnector(
        provider=StubEbayBrowseProvider({"itemSummaries": [item_summary]}),
        settings=EbaySettings(
            client_id=None,
            client_secret=None,
            oauth_token=None,
            oauth_scopes=("https://api.ebay.com/oauth/api_scope",),
            detail_fieldgroups=("PRODUCT", "ADDITIONAL_SELLER_DETAILS"),
            environment="production",
            site_id="EBAY_US",
            end_user_context=None,
            request_timeout_seconds=10.0,
            page_size=25,
        ),
    )

    page = connector.search(query="macbook pro 14")
    event = page.items[0]

    assert event.source == "ebay"
    assert event.source_listing_id == "v1|1234567890|0"
    assert event.price == 899.0
    assert event.shipping_price == 19.99
    assert event.brand == "Apple"
    assert event.model_text == "MacBook Pro 14"
    assert len(event.images) == 2
    assert event.category_path[-1] == "Laptops & Netbooks"


def test_ebay_hydrated_item_merges_detail_fields(fixture_loader) -> None:
    item_summary = fixture_loader("ebay_item_summary.json")
    item_detail = fixture_loader("ebay_item_detail.json")
    connector = EbayConnector(
        provider=StubEbayBrowseProvider(
            {"itemSummaries": [item_summary]},
            item_details_by_id={"v1|1234567890|0": item_detail},
        ),
        settings=EbaySettings(
            client_id=None,
            client_secret=None,
            oauth_token=None,
            oauth_scopes=("https://api.ebay.com/oauth/api_scope",),
            detail_fieldgroups=("PRODUCT", "ADDITIONAL_SELLER_DETAILS"),
            environment="production",
            site_id="EBAY_US",
            end_user_context=None,
            request_timeout_seconds=10.0,
            page_size=25,
        ),
    )

    page = connector.search(query="macbook pro 14", hydrate_details=True)
    event = page.items[0]

    assert "Minor lid wear" in (event.description or "")
    assert event.location_text == "Brooklyn, NY, US"
    assert event.quantity == 1
    assert len(event.images) == 3
    assert isinstance(event.raw_payload, dict)
    assert event.raw_payload["details"]["itemId"] == "v1|1234567890|0"


def test_ebay_oauth_provider_mints_and_caches_application_tokens() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "test-token",
                "expires_in": 7200,
                "token_type": "Bearer",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = EbaySettings(
        client_id="client-id",
        client_secret="client-secret",
        oauth_token=None,
        oauth_scopes=("https://api.ebay.com/oauth/api_scope",),
        detail_fieldgroups=("PRODUCT",),
        environment="sandbox",
        site_id="EBAY_US",
        end_user_context=None,
        request_timeout_seconds=10.0,
        page_size=25,
    )
    provider = EbayOAuthTokenProvider(settings=settings, client=client)

    first = provider.get_token()
    second = provider.get_token()

    assert first == "test-token"
    assert second == "test-token"
    assert len(calls) == 1
    assert str(calls[0].url) == "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    assert (
        calls[0].headers["Authorization"]
        == "Basic " + base64.b64encode(b"client-id:client-secret").decode()
    )
    assert calls[0].content.decode() == (
        "grant_type=client_credentials&scope=https%3A%2F%2Fapi.ebay.com%2Foauth%2Fapi_scope"
    )
