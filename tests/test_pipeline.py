from __future__ import annotations

from scanner.libs.events.bus import Topics
from scanner.libs.schemas import ActionRoute, IngestTestListingRequest
from scanner.libs.storage.repositories import UnderwritingRepository


def test_pipeline_ingests_and_underwrites_profitable_listing(test_container) -> None:
    request = IngestTestListingRequest(
        source="test",
        source_listing_id="macbook-good-deal",
        title="Apple MacBook Pro 14 M1 Pro 16GB 1TB with charger",
        description="Great condition. Includes charger and box. Need gone today.",
        price=500.0,
        shipping_price=0.0,
        category_path=["laptops", "apple"],
        seller_id="seller-1",
    )

    with test_container.session_scope() as session:
        pipeline = test_container.pipeline(session)
        event = pipeline.build_raw_event(request)
        listing = pipeline.ingest(event)
        result = pipeline.underwrite(listing.listing_pk)

        stored = UnderwritingRepository(session).get(listing.listing_pk)

    assert result.route == ActionRoute.PRIORITY_ALERT
    assert stored is not None
    assert stored.canonical_asset.asset_id == "apple-macbook-pro-14-m1-pro-16-1tb"
    alerts = test_container.bus.consume(Topics.ALERTS)
    assert len(alerts) == 1
