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


def test_craigslist_connector_parses_result_cards_from_static_html() -> None:
    connector = CraigslistConnector(
        settings=CraigslistSettings(
            anchors=(CraigslistAnchor(label="New York", site="newyork", postal_code="10001"),),
            category="sya",
            delivery_available=True,
            search_distance=500,
            default_query="macbook",
            request_timeout_seconds=10.0,
        )
    )
    html = """
    <ol class="cl-static-search-results">
      <li class="cl-static-search-result" title="MacBook Air 13">
        <a href="https://newyork.craigslist.org/brk/sys/d/brooklyn-macbook-air-13/7921111111.html">
          <div class="title">MacBook Air 13</div>
          <div class="details">
            <div class="price">$450</div>
            <div class="location">Brooklyn</div>
          </div>
        </a>
      </li>
      <li class="cl-static-search-result" title="ThinkPad T14">
        <a href="https://newyork.craigslist.org/mnh/sys/d/manhattan-thinkpad-t14/7922222222.html">
          <div class="title">ThinkPad T14</div>
          <div class="details">
            <div class="price">$525</div>
            <div class="location">Manhattan</div>
          </div>
        </a>
      </li>
    </ol>
    """

    items = connector.parse_result_cards(
        html,
        page_url="https://newyork.craigslist.org/search/sya?delivery_available=1",
        source_label="New York",
    )

    assert len(items) == 2
    assert items[0].source_listing_id == "7921111111"
    assert items[0].title == "MacBook Air 13"
    assert items[0].price == 450.0
    assert items[0].location_text == "Brooklyn"


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
