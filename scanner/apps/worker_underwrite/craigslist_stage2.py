from __future__ import annotations

import json
import os

import httpx

from scanner.libs.connectors.craigslist import CraigslistConnector
from scanner.libs.schemas import DetailGateDecision, FulfillmentStatus, LotAnalysis, TriageDecision
from scanner.libs.services.container import ApplicationContainer
from scanner.libs.storage.repositories import ListingRepository, TriageRepository
from scanner.libs.utils.logging import get_logger

logger = get_logger(__name__)


def _build_fetch_failure_decision(exc: Exception) -> DetailGateDecision:
    return DetailGateDecision(
        should_download_photos=False,
        fulfillment_status=FulfillmentStatus.UNKNOWN,
        exclusion_reason="detail_fetch_failed",
        reasons=[f"Failed to fetch Craigslist detail page: {exc!s}"],
    )


def run_once(*, limit: int | None = None) -> dict:
    container = ApplicationContainer()
    container.ensure_database()
    include_unknown_rechecks = (
        os.getenv("CRAIGSLIST_STAGE2_RECHECK_UNKNOWN", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    connector = container.connector_registry.create("craigslist")
    if not isinstance(connector, CraigslistConnector):
        raise RuntimeError("Craigslist connector registry returned an unexpected connector type.")

    processed = 0
    shippable = 0
    pickup_only = 0
    unknown = 0
    examples: list[dict] = []

    with container.session_scope() as session:
        triage_repository = TriageRepository(session)
        listing_repository = ListingRepository(session)
        candidates = triage_repository.list_detail_gate_candidates(
            source="craigslist",
            limit=limit,
            include_unknown_rechecks=include_unknown_rechecks,
        )

        for listing, triage_row in candidates:
            event = listing_repository.get_event(listing.listing_pk)
            if event is None or not event.listing_url:
                continue

            stage_zero = TriageDecision.model_validate(triage_row.stage_zero_json)
            lot_analysis = LotAnalysis.model_validate(triage_row.lot_analysis_json)
            llm_triage = triage_row.llm_triage_json

            try:
                detailed_event = connector.hydrate_listing_detail(event)
                listing_repository.upsert_event(detailed_event)
                detail_gate = container.detail_gate.evaluate(detailed_event)
            except (httpx.HTTPError, ValueError) as exc:
                detail_gate = _build_fetch_failure_decision(exc)

            triage_repository.save(
                listing_pk=listing.listing_pk,
                stage_zero=stage_zero,
                lot_analysis=lot_analysis,
                detail_gate=detail_gate,
            )

            processed += 1
            if detail_gate.fulfillment_status == FulfillmentStatus.SHIPPABLE:
                shippable += 1
            elif detail_gate.fulfillment_status == FulfillmentStatus.PICKUP_ONLY:
                pickup_only += 1
            else:
                unknown += 1

            if len(examples) < 10:
                examples.append(
                    {
                        "listing_pk": listing.listing_pk,
                        "title": listing.title,
                        "listing_url": listing.listing_url,
                        "needs_detail_fetch": (llm_triage or {}).get("needs_detail_fetch"),
                        "should_download_photos": detail_gate.should_download_photos,
                        "fulfillment_status": detail_gate.fulfillment_status,
                        "exclusion_reason": detail_gate.exclusion_reason,
                        "reasons": detail_gate.reasons,
                    }
                )

    summary = {
        "processed": processed,
        "shippable": shippable,
        "pickup_only": pickup_only,
        "unknown": unknown,
        "include_unknown_rechecks": include_unknown_rechecks,
        "examples": examples,
    }
    logger.info("craigslist_stage2.completed", **summary)
    return summary


if __name__ == "__main__":
    raw_limit = os.getenv("CRAIGSLIST_STAGE2_LIMIT")
    result = run_once(limit=int(raw_limit) if raw_limit else None)
    print(json.dumps(result, indent=2))
