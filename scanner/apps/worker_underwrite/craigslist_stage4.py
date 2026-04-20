from __future__ import annotations

import json
import os

from scanner.libs.connectors.ebay import EbayConnector
from scanner.libs.schemas import LotAnalysis, PhotoReviewResult, TriageDecision
from scanner.libs.services.container import ApplicationContainer
from scanner.libs.storage.repositories import ListingRepository, TriageRepository
from scanner.libs.utils.logging import get_logger
from scanner.libs.valuation.market_check import EbayMarketCheckService

logger = get_logger(__name__)


def run_once(*, limit: int | None = None) -> dict:
    container = ApplicationContainer()
    container.ensure_database()
    ebay_connector = container.connector_registry.create("ebay")
    if not isinstance(ebay_connector, EbayConnector):
        raise RuntimeError("eBay connector registry returned an unexpected connector type.")

    service = EbayMarketCheckService(ebay_connector)
    include_existing_rechecks = (
        os.getenv("CRAIGSLIST_STAGE4_RECHECK_EXISTING", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )

    processed = 0
    with_matches = 0
    without_matches = 0
    examples: list[dict] = []

    with container.session_scope() as session:
        triage_repository = TriageRepository(session)
        listing_repository = ListingRepository(session)
        candidates = triage_repository.list_market_check_candidates(
            source="craigslist",
            limit=limit,
            include_existing_rechecks=include_existing_rechecks,
        )

        for listing, triage_row in candidates:
            event = listing_repository.get_event(listing.listing_pk)
            if event is None:
                continue

            canonical_asset = container.entity_resolution.resolve(event)
            photo_review = PhotoReviewResult.model_validate(triage_row.photo_review_json)
            market_check = service.run(
                event=event,
                candidate=canonical_asset,
                photo_review=photo_review,
            )

            triage_repository.save(
                listing_pk=listing.listing_pk,
                stage_zero=TriageDecision.model_validate(triage_row.stage_zero_json),
                lot_analysis=LotAnalysis.model_validate(triage_row.lot_analysis_json),
                market_check=market_check,
            )

            processed += 1
            if market_check.match_count:
                with_matches += 1
            else:
                without_matches += 1

            if len(examples) < 10:
                examples.append(
                    {
                        "listing_pk": listing.listing_pk,
                        "title": listing.title,
                        "query": market_check.query,
                        "match_count": market_check.match_count,
                        "fast_sale_estimate": market_check.fast_sale_estimate,
                        "price_low": market_check.price_low,
                        "price_median": market_check.price_median,
                        "confidence": market_check.confidence,
                    }
                )

    summary = {
        "processed": processed,
        "with_matches": with_matches,
        "without_matches": without_matches,
        "include_existing_rechecks": include_existing_rechecks,
        "examples": examples,
    }
    logger.info("craigslist_stage4.completed", **summary)
    return summary


if __name__ == "__main__":
    raw_limit = os.getenv("CRAIGSLIST_STAGE4_LIMIT")
    result = run_once(limit=int(raw_limit) if raw_limit else None)
    print(json.dumps(result, indent=2))
