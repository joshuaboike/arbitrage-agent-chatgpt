from __future__ import annotations

from datetime import UTC, datetime

from scanner.libs.nlp.entity_resolution import EntityResolutionService
from scanner.libs.schemas import EventType, RawListingEvent
from scanner.libs.taxonomy.service import TaxonomyService


def test_entity_resolution_maps_seeded_macbook_asset() -> None:
    service = EntityResolutionService(TaxonomyService())
    event = RawListingEvent(
        event_id="evt-1",
        source="test",
        source_listing_id="listing-1",
        event_type=EventType.CREATE,
        observed_at=datetime.now(UTC),
        title="Apple MacBook Pro 14 M1 Pro 16GB 1TB Space Black with charger",
        description="Excellent condition. Includes original charger and box.",
        price=899.0,
        currency="USD",
        images=[],
        category_path=["laptops"],
        raw_payload={},
    )

    candidate = service.resolve(event)

    assert candidate.asset_id == "apple-macbook-pro-14-m1-pro-16-1tb"
    assert candidate.asset_family_id == "apple-macbook-pro-14-m1-pro"
    assert candidate.specs.storage_gb == 1024
    assert candidate.specs.ram_gb == 16
    assert candidate.bundle.charger is True
    assert candidate.confidence >= 0.8
