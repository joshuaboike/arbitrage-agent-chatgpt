from __future__ import annotations

import json
import os

from scanner.libs.schemas import LotAnalysis, TriageDecision
from scanner.libs.services.container import ApplicationContainer
from scanner.libs.storage.repositories import ListingRepository, TriageRepository
from scanner.libs.utils.logging import get_logger

logger = get_logger(__name__)


def run_once(*, limit: int | None = None) -> dict:
    container = ApplicationContainer()
    container.ensure_database()
    if not container.openai_stage_one_triage.is_configured:
        raise RuntimeError("OPENAI_API_KEY is required to run Craigslist Stage 1 triage.")

    processed = 0
    accepted_for_detail = 0
    rejected = 0
    examples: list[dict] = []

    with container.session_scope() as session:
        triage_repository = TriageRepository(session)
        listing_repository = ListingRepository(session)
        candidates = triage_repository.list_stage_one_candidates(
            source="craigslist",
            limit=limit,
        )

        for listing, triage_row in candidates:
            event = listing_repository.get_event(listing.listing_pk)
            if event is None:
                continue
            stage_zero = TriageDecision.model_validate(triage_row.stage_zero_json)
            lot_analysis = LotAnalysis.model_validate(triage_row.lot_analysis_json)
            llm_triage = container.openai_stage_one_triage.evaluate(
                event=event,
                stage_zero=stage_zero,
                lot_analysis=lot_analysis,
            )
            triage_repository.save(
                listing_pk=listing.listing_pk,
                stage_zero=stage_zero,
                lot_analysis=lot_analysis,
                detail_gate=None,
                llm_triage=llm_triage,
                llm_model=container.settings.openai_stage1_model,
            )
            processed += 1
            if llm_triage.needs_detail_fetch:
                accepted_for_detail += 1
            else:
                rejected += 1

            if len(examples) < 10:
                examples.append(
                    {
                        "listing_pk": listing.listing_pk,
                        "title": listing.title,
                        "price": listing.price,
                        "family": llm_triage.family,
                        "is_candidate": llm_triage.is_candidate,
                        "needs_detail_fetch": llm_triage.needs_detail_fetch,
                        "triage_score": llm_triage.triage_score,
                        "confidence": llm_triage.confidence,
                        "reason": llm_triage.reason,
                        "risk_flags": llm_triage.risk_flags,
                    }
                )

    summary = {
        "processed": processed,
        "accepted_for_detail": accepted_for_detail,
        "rejected": rejected,
        "model": container.settings.openai_stage1_model,
        "examples": examples,
    }
    logger.info("craigslist_stage1.completed", **summary)
    return summary


if __name__ == "__main__":
    raw_limit = os.getenv("CRAIGSLIST_STAGE1_LIMIT")
    result = run_once(
        limit=int(raw_limit) if raw_limit else None
    )
    print(json.dumps(result, indent=2))
