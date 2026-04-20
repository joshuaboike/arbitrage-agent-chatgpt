from __future__ import annotations

from scanner.libs.nlp.lots import LotAnalyzer
from scanner.libs.schemas import (
    DetailGateDecision,
    EventType,
    FulfillmentStatus,
    LlmTriageDecision,
    PhotoReviewResult,
    RawListingEvent,
)
from scanner.libs.storage.repositories import ListingRepository, TriageRepository
from scanner.libs.valuation.market_check import EbayMarketCheckService


class FakeEbayConnector:
    def __init__(self, items: list[RawListingEvent]) -> None:
        self.items = items
        self.queries: list[str] = []

    def search(self, *, query: str, hydrate_details: bool = False):  # noqa: ANN003
        self.queries.append(query)

        class Page:
            def __init__(self, items: list[RawListingEvent]) -> None:
                self.items = items

        return Page(self.items)


def _build_craigslist_event() -> RawListingEvent:
    return RawListingEvent(
        event_id="evt-cl-1",
        source="craigslist",
        source_listing_id="cl-1",
        event_type=EventType.CREATE,
        observed_at="2026-04-20T12:00:00Z",
        listing_url="https://example.com/craigslist/1",
        title="MacBook Pro 14 M1 Pro 16GB 1TB",
        description="Great condition, charger included.",
        price=850.0,
        currency="USD",
        images=["https://images.craigslist.org/one_600x450.jpg"],
        attributes={"search_delivery_filter_applied": True},
    )


def _build_ebay_item(
    source_listing_id: str,
    title: str,
    price: float,
    shipping_price: float = 0.0,
) -> RawListingEvent:
    return RawListingEvent(
        event_id=f"evt-{source_listing_id}",
        source="ebay",
        source_listing_id=source_listing_id,
        event_type=EventType.CREATE,
        observed_at="2026-04-20T12:00:00Z",
        listing_url=f"https://example.com/ebay/{source_listing_id}",
        title=title,
        price=price,
        shipping_price=shipping_price,
        currency="USD",
    )


def test_market_check_service_builds_query_and_summarizes_matches(test_container) -> None:
    craigslist_event = _build_craigslist_event()
    candidate = test_container.entity_resolution.resolve(craigslist_event)
    photo_review = PhotoReviewResult(
        downloaded_photo_count=5,
        unique_photo_count=5,
        photo_quality_score=0.9,
        device_visibility_score=0.9,
        confidence=0.8,
        condition_band="B/C",
    )

    fake_connector = FakeEbayConnector(
        [
            _build_ebay_item(
                "eb-1",
                'Apple MacBook Pro 14" M1 Pro 16GB 1TB 2021',
                1199.0,
                25.0,
            ),
            _build_ebay_item(
                "eb-2",
                'Apple MacBook Pro 14" M1 Pro 16GB 512GB',
                1099.0,
                20.0,
            ),
            _build_ebay_item(
                "eb-3",
                "Dell XPS 13 16GB 512GB",
                799.0,
                15.0,
            ),
        ]
    )
    service = EbayMarketCheckService(fake_connector)  # type: ignore[arg-type]

    result = service.run(
        event=craigslist_event,
        candidate=candidate,
        photo_review=photo_review,
    )

    assert fake_connector.queries
    assert "MacBook Pro 14" in fake_connector.queries[0]
    assert result.match_count == 2
    assert result.fast_sale_estimate is not None
    assert result.price_low is not None
    assert result.price_median is not None
    assert all("Dell XPS" not in title for title in result.comparable_titles)


def test_triage_repository_lists_market_check_candidates(test_container) -> None:
    with test_container.session_scope() as session:
        listing_repository = ListingRepository(session)
        triage_repository = TriageRepository(session)
        event = _build_craigslist_event()
        listing = listing_repository.upsert_event(event)
        stage_zero = test_container.stage_zero_triage.evaluate(event)
        lot_analysis = LotAnalyzer().analyze(event)
        llm_triage = LlmTriageDecision(
            is_candidate=True,
            item_type="laptop",
            brand="Apple",
            family="MacBook Pro",
            variant_hint="14-inch",
            condition_guess="used_good",
            risk_flags=[],
            needs_detail_fetch=True,
            triage_score=0.9,
            confidence=0.84,
            reason="Looks promising.",
        )
        detail_gate = DetailGateDecision(
            should_download_photos=True,
            fulfillment_status=FulfillmentStatus.UNKNOWN,
            reasons=["Advances because search used delivery filter."],
        )
        photo_review = PhotoReviewResult(
            downloaded_photo_count=5,
            unique_photo_count=5,
            photo_quality_score=0.9,
            device_visibility_score=0.9,
            confidence=0.8,
            condition_band="B/C",
        )

        triage_repository.save(
            listing_pk=listing.listing_pk,
            stage_zero=stage_zero,
            lot_analysis=lot_analysis,
            llm_triage=llm_triage,
            llm_model="gpt-4o-mini",
            detail_gate=detail_gate,
            photo_review=photo_review,
        )

        candidates = triage_repository.list_market_check_candidates(source="craigslist")
        assert len(candidates) == 1

        service = EbayMarketCheckService(
            FakeEbayConnector(
                [
                    _build_ebay_item(
                        "eb-1",
                        'Apple MacBook Pro 14" M1 Pro 16GB 1TB 2021',
                        1199.0,
                        25.0,
                    )
                ]
            )
        )
        market_check = service.run(
            event=event,
            candidate=test_container.entity_resolution.resolve(event),
            photo_review=photo_review,
        )
        triage_repository.save(
            listing_pk=listing.listing_pk,
            stage_zero=stage_zero,
            lot_analysis=lot_analysis,
            market_check=market_check,
        )

        assert triage_repository.list_market_check_candidates(source="craigslist") == []
