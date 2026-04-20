from __future__ import annotations

from scanner.libs.connectors.craigslist import CraigslistConnector
from scanner.libs.nlp.lots import LotAnalyzer
from scanner.libs.nlp.triage import CraigslistDetailGateService, StageZeroTriageService
from scanner.libs.schemas import FulfillmentStatus, RawListingEvent
from scanner.libs.utils.config import CraigslistAnchor, CraigslistSettings


def _build_event(
    *,
    title: str,
    listing_url: str = "https://newyork.craigslist.org/sys/d/example/123.html",
    price: float = 700.0,
    description: str | None = None,
) -> RawListingEvent:
    return RawListingEvent(
        event_id="evt-1",
        source="craigslist",
        source_listing_id="cl-123",
        event_type="CREATE",
        observed_at="2026-04-20T12:00:00Z",
        listing_url=listing_url,
        title=title,
        description=description,
        price=price,
        currency="USD",
    )


def test_craigslist_connector_builds_encoded_anchor_searches() -> None:
    connector = CraigslistConnector(
        settings=CraigslistSettings(
            anchors=(
                CraigslistAnchor(label="New York", site="newyork", postal_code="10001"),
                CraigslistAnchor(label="Chicago", site="chicago", postal_code="60601"),
            ),
            category="sya",
            delivery_available=True,
            search_distance=500,
            default_query='(macbook|thinkpad|"mac mini") -parts',
            request_timeout_seconds=10.0,
        )
    )

    searches = connector.build_anchor_searches()

    assert len(searches) == 2
    assert searches[0].url.startswith("https://newyork.craigslist.org/search/sya?")
    assert "delivery_available=1" in searches[0].url
    assert "postal=10001" in searches[0].url
    assert "search_distance=500" in searches[0].url
    assert "query=%28macbook%7Cthinkpad%7C%22mac+mini%22%29+-parts" in searches[0].url


def test_stage_zero_triage_rejects_out_of_scope_or_bad_price() -> None:
    service = StageZeroTriageService()

    decision = service.evaluate(_build_event(title="Desktop gaming rig", price=650.0))
    assert decision.accepted is False
    assert decision.reject_reason == "missing_device_token"

    too_cheap = service.evaluate(_build_event(title="MacBook Air M1", price=40.0))
    assert too_cheap.accepted is False
    assert too_cheap.reject_reason == "price_out_of_bounds"


def test_detail_gate_rejects_pickup_only_and_keeps_shippable() -> None:
    service = CraigslistDetailGateService()

    rejected = service.evaluate(
        _build_event(
            title="MacBook Pro 14",
            description="Excellent condition. Pickup only in Brooklyn.",
        )
    )
    assert rejected.should_download_photos is False
    assert rejected.fulfillment_status == FulfillmentStatus.PICKUP_ONLY
    assert rejected.exclusion_reason == "pickup_only"

    accepted = service.evaluate(
        _build_event(
            title="ThinkPad X1 Carbon",
            description="Delivery available and can ship tomorrow.",
        )
    )
    assert accepted.should_download_photos is True
    assert accepted.fulfillment_status == FulfillmentStatus.SHIPPABLE


def test_lot_analyzer_flags_multi_item_bundles_for_split_valuation() -> None:
    analyzer = LotAnalyzer()

    analysis = analyzer.analyze(
        _build_event(
            title="MacBook Air + Mac mini bundle",
            description="Selling both together. Charger included.",
        )
    )

    assert analysis.is_multi_item is True
    assert analysis.should_split_valuation is True
    assert len(analysis.component_candidates) >= 2
