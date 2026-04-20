from __future__ import annotations

import json
import os

from scanner.libs.services.container import ApplicationContainer
from scanner.libs.storage.repositories import ListingRepository, TriageRepository


def run_smoke(
    *,
    anchor_label: str = "New York",
    max_pages: int = 2,
    persist: bool = True,
) -> dict:
    container = ApplicationContainer()
    container.ensure_database()
    connector = container.connector_registry.create("craigslist")
    searches = connector.build_anchor_searches()
    search = next((item for item in searches if item.label == anchor_label), searches[0])

    per_page: list[dict] = []
    overall_seen_ids: set[str] = set()
    accepted_ids: set[str] = set()
    lot_candidate_ids: set[str] = set()
    persisted_listing_pks: set[str] = set()

    with container.session_scope() as session:
        listings = ListingRepository(session)
        triage_repository = TriageRepository(session)

        for page_index in range(max_pages):
            offset = page_index * 120
            records = connector.fetch_result_cards(search, offset=offset)
            unique_before = len(overall_seen_ids)
            stage_zero_page_accepts = 0
            lot_page_candidates = 0

            for record in records:
                if record.source_listing_id not in overall_seen_ids:
                    overall_seen_ids.add(record.source_listing_id)
                triage = container.stage_zero_triage.evaluate(record)
                if triage.accepted:
                    accepted_ids.add(record.source_listing_id)
                    stage_zero_page_accepts += 1
                lot_analysis = container.lot_analyzer.analyze(record)
                if lot_analysis.should_split_valuation:
                    lot_candidate_ids.add(record.source_listing_id)
                    lot_page_candidates += 1

                if persist:
                    listing = listings.upsert_event(record)
                    triage_repository.save(
                        listing_pk=listing.listing_pk,
                        stage_zero=triage,
                        lot_analysis=lot_analysis,
                    )
                    persisted_listing_pks.add(listing.listing_pk)

            page_sample = [
                {
                    "source_listing_id": record.source_listing_id,
                    "title": record.title,
                    "price": record.price,
                    "location_text": record.location_text,
                }
                for record in records[:5]
            ]
            per_page.append(
                {
                    "page_number": page_index + 1,
                    "offset": offset,
                    "page_url": connector.build_page_url(search, offset=offset),
                    "parsed_cards": len(records),
                    "new_unique_cards": len(overall_seen_ids) - unique_before,
                    "duplicate_cards": len(records) - (len(overall_seen_ids) - unique_before),
                    "stage_zero_accepts": stage_zero_page_accepts,
                    "lot_split_candidates": lot_page_candidates,
                    "sample": page_sample,
                }
            )

    return {
        "anchor_label": search.label,
        "base_search_url": search.url,
        "pages_requested": max_pages,
        "persisted": persist,
        "persisted_listings": len(persisted_listing_pks),
        "unique_cards": len(overall_seen_ids),
        "unique_stage_zero_accepts": len(accepted_ids),
        "unique_lot_split_candidates": len(lot_candidate_ids),
        "pages": per_page,
    }


if __name__ == "__main__":
    summary = run_smoke(
        anchor_label=os.getenv("CRAIGSLIST_SMOKE_LABEL", "New York"),
        max_pages=int(os.getenv("CRAIGSLIST_SMOKE_PAGES", "2")),
        persist=os.getenv("CRAIGSLIST_SMOKE_PERSIST", "true").strip().lower()
        in {"1", "true", "yes", "on"},
    )
    print(json.dumps(summary, indent=2))
