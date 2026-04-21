from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from scanner.libs.schemas import DetailGateDecision, FulfillmentStatus, PhotoReviewResult
from scanner.libs.services.container import ApplicationContainer
from scanner.libs.valuation.market_check import EbayMarketCheckService
from scanner.libs.vision.review import PhotoReviewService


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class UsageRecord:
    model: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int


class UsageTrackingClient:
    def __init__(self, base_client: httpx.Client) -> None:
        self._base_client = base_client
        self.records: list[UsageRecord] = []

    def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
        response = self._base_client.post(*args, **kwargs)
        self._capture(response)
        return response

    def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return self._base_client.get(*args, **kwargs)

    def _capture(self, response: httpx.Response) -> None:
        if "/v1/responses" not in str(response.request.url):
            return
        try:
            payload = response.json()
        except ValueError:
            return
        usage = payload.get("usage") or {}
        input_details = usage.get("input_tokens_details") or {}
        self.records.append(
            UsageRecord(
                model=payload.get("model"),
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                total_tokens=int(usage.get("total_tokens") or 0),
                cached_input_tokens=int(input_details.get("cached_tokens") or 0),
            )
        )

    def __getattr__(self, item: str) -> Any:
        return getattr(self._base_client, item)


class ProgressTracker:
    def __init__(self, *, total: int, phase: str, emit_every: int = 10) -> None:
        self.total = max(total, 0)
        self.phase = phase
        self.emit_every = max(emit_every, 1)
        self.started_at = time.perf_counter()
        self.processed = 0

    def advance(self, *, current_title: str | None = None, force: bool = False) -> None:
        self.processed += 1
        if not force and self.processed % self.emit_every != 0 and self.processed != self.total:
            return
        elapsed = max(time.perf_counter() - self.started_at, 0.001)
        rate_per_minute = (self.processed / elapsed) * 60.0
        remaining = max(self.total - self.processed, 0)
        eta_minutes = (remaining / (self.processed / elapsed)) / 60.0 if self.processed else None
        payload = {
            "progress": {
                "phase": self.phase,
                "processed": self.processed,
                "total": self.total,
                "percent_complete": round((self.processed / self.total) * 100, 1)
                if self.total
                else 100.0,
                "rate_per_minute": round(rate_per_minute, 2),
                "eta_minutes": round(eta_minutes, 2) if eta_minutes is not None else None,
                "current_title": current_title,
            }
        }
        print(json.dumps(payload), flush=True)


def usage_summary(records: list[UsageRecord]) -> dict[str, Any]:
    return {
        "calls": len(records),
        "models": sorted({record.model for record in records if record.model}),
        "input_tokens": sum(record.input_tokens for record in records),
        "output_tokens": sum(record.output_tokens for record in records),
        "total_tokens": sum(record.total_tokens for record in records),
        "cached_input_tokens": sum(record.cached_input_tokens for record in records),
    }


def build_fetch_failure_decision(exc: Exception) -> DetailGateDecision:
    return DetailGateDecision(
        should_download_photos=False,
        fulfillment_status=FulfillmentStatus.UNKNOWN,
        exclusion_reason="detail_fetch_failed",
        reasons=[f"Failed to fetch Craigslist detail page: {exc!s}"],
    )


def rough_gap(
    *,
    ask_price: float | None,
    fast_sale_estimate: float | None,
    cost_breakdown: dict[str, Any],
) -> float | None:
    if ask_price is None or fast_sale_estimate is None:
        return None
    return round(
        fast_sale_estimate
        - ask_price
        - float(cost_breakdown.get("acquisition_costs") or 0.0)
        - float(cost_breakdown.get("exit_costs") or 0.0)
        - float(cost_breakdown.get("carry_costs") or 0.0)
        - float(cost_breakdown.get("refurb_expected_cost") or 0.0),
        2,
    )


def listing_summary(
    *,
    page_label: str,
    event_title: str | None,
    event_price: float | None,
    location_text: str | None,
    listing_url: str | None,
    stage_zero: dict[str, Any] | None = None,
    llm_triage: dict[str, Any] | None = None,
    detail_gate: dict[str, Any] | None = None,
    photo_review: PhotoReviewResult | None = None,
    canonical_candidate: dict[str, Any] | None = None,
    market_check: dict[str, Any] | None = None,
    costs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "anchor_label": page_label,
        "title": event_title,
        "ask_price": event_price,
        "location_text": location_text,
        "listing_url": listing_url,
        "stage_zero": stage_zero,
        "llm_triage": llm_triage,
        "detail_gate": detail_gate,
        "photo_review": photo_review.model_dump(mode="json") if photo_review else None,
        "canonical_candidate": canonical_candidate,
        "market_check": market_check,
        "costs": costs,
        "rough_post_fee_gap": rough_gap(
            ask_price=event_price,
            fast_sale_estimate=(market_check or {}).get("fast_sale_estimate"),
            cost_breakdown=costs or {},
        ),
    }


def run_stack_smoke(
    *,
    anchor_labels: list[str],
    pages_per_anchor: int,
    report_dir: Path,
    max_stage0_accepts: int | None = None,
    progress_every: int = 10,
) -> dict[str, Any]:
    load_env_file(Path(".env"))
    container = ApplicationContainer()
    craigslist = container.connector_registry.create("craigslist")
    ebay = container.connector_registry.create("ebay")
    market_service = EbayMarketCheckService(ebay)

    stage1_client = UsageTrackingClient(
        httpx.Client(timeout=container.settings.openai_request_timeout_seconds)
    )
    container.openai_stage_one_triage.client = stage1_client

    report_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    image_cache_dir = report_dir / f"images_{report_stamp}"
    review_cache_dir = report_dir / f"photo_reviews_{report_stamp}"
    stage3_client = UsageTrackingClient(httpx.Client(timeout=30.0, follow_redirects=True))
    photo_service = PhotoReviewService(
        cache_dir=image_cache_dir,
        review_cache_dir=review_cache_dir,
        openai_api_key=container.settings.openai_api_key,
        openai_model=os.getenv("OPENAI_STAGE3_MODEL", "gpt-4.1-mini"),
        client=stage3_client,
    )

    searches = craigslist.build_anchor_searches()
    selected_searches = [
        search for search in searches if search.label in set(anchor_labels)
    ] or searches[: len(anchor_labels)]

    fetched_pages: list[dict[str, Any]] = []
    unique_records: dict[str, tuple[str, Any]] = {}
    fetch_tracker = ProgressTracker(
        total=len(selected_searches) * pages_per_anchor,
        phase="acquisition",
        emit_every=1,
    )

    for search in selected_searches:
        for page_index in range(pages_per_anchor):
            offset = page_index * 120
            page_url = craigslist.build_page_url(search, offset=offset)
            records = craigslist.fetch_result_cards(search, offset=offset)
            before = len(unique_records)
            for record in records:
                unique_records.setdefault(record.source_listing_id, (search.label, record))
            fetched_pages.append(
                {
                    "anchor_label": search.label,
                    "offset": offset,
                    "page_url": page_url,
                    "parsed_cards": len(records),
                    "new_unique_cards": len(unique_records) - before,
                }
            )
            fetch_tracker.advance(current_title=search.label)

    stage0_candidates: list[tuple[str, Any, Any, Any]] = []
    stage0_tracker = ProgressTracker(
        total=len(unique_records),
        phase="stage0",
        emit_every=progress_every,
    )

    for anchor_label, record in unique_records.values():
        stage_zero = container.stage_zero_triage.evaluate(record)
        lot_analysis = container.lot_analyzer.analyze(record)
        if stage_zero.accepted:
            stage0_candidates.append((anchor_label, record, stage_zero, lot_analysis))
        stage0_tracker.advance(current_title=record.title)

    counts = {
        "raw_unique_cards": len(unique_records),
        "stage0_accepts": 0,
        "stage1_detail_fetch": 0,
        "stage1_rejects": 0,
        "stage2_should_download": 0,
        "stage2_shippable": 0,
        "stage2_pickup_only": 0,
        "stage2_unknown": 0,
        "stage2_fetch_failures": 0,
        "stage3_reviewed": 0,
        "stage3_no_photos": 0,
        "stage4_with_matches": 0,
        "stage4_without_matches": 0,
        "positive_gap_candidates": 0,
    }

    survivors: list[dict[str, Any]] = []
    deep_total = (
        min(len(stage0_candidates), max_stage0_accepts)
        if max_stage0_accepts is not None
        else len(stage0_candidates)
    )
    deep_tracker = ProgressTracker(
        total=deep_total,
        phase="stage1_to_stage4",
        emit_every=progress_every,
    )

    for anchor_label, record, stage_zero, lot_analysis in stage0_candidates:
        if max_stage0_accepts is not None and counts["stage0_accepts"] >= max_stage0_accepts:
            continue

        counts["stage0_accepts"] += 1
        current_title = record.title
        try:
            llm_triage = container.openai_stage_one_triage.evaluate(
                event=record,
                stage_zero=stage_zero,
                lot_analysis=lot_analysis,
            )
            if not llm_triage.needs_detail_fetch:
                counts["stage1_rejects"] += 1
                continue
            counts["stage1_detail_fetch"] += 1

            try:
                detailed_event = craigslist.hydrate_listing_detail(record)
                detail_gate = container.detail_gate.evaluate(detailed_event)
            except (httpx.HTTPError, ValueError) as exc:
                detailed_event = record
                detail_gate = build_fetch_failure_decision(exc)

            current_title = detailed_event.title or current_title

            if detail_gate.exclusion_reason == "detail_fetch_failed":
                counts["stage2_fetch_failures"] += 1
            if detail_gate.fulfillment_status == FulfillmentStatus.SHIPPABLE:
                counts["stage2_shippable"] += 1
            elif detail_gate.fulfillment_status == FulfillmentStatus.PICKUP_ONLY:
                counts["stage2_pickup_only"] += 1
            else:
                counts["stage2_unknown"] += 1

            if not detail_gate.should_download_photos:
                continue

            counts["stage2_should_download"] += 1
            downloaded = [
                photo
                for image_url in detailed_event.images[: photo_service.max_images]
                for photo in [photo_service.download_photo(image_url)]
                if photo is not None
            ]
            photo_review = photo_service.review(downloaded)
            if photo_review.downloaded_photo_count:
                counts["stage3_reviewed"] += 1
            else:
                counts["stage3_no_photos"] += 1

            canonical = container.entity_resolution.resolve(
                detailed_event,
                photo_review=photo_review,
                llm_triage=llm_triage,
            )
            market_check = market_service.run(
                event=detailed_event,
                candidate=canonical,
                photo_review=photo_review,
            )
            if market_check.match_count:
                counts["stage4_with_matches"] += 1
            else:
                counts["stage4_without_matches"] += 1

            costs = container.cost_engine.estimate(detailed_event).model_dump(mode="json")
            summary = listing_summary(
                page_label=anchor_label,
                event_title=detailed_event.title,
                event_price=detailed_event.price,
                location_text=detailed_event.location_text,
                listing_url=detailed_event.listing_url,
                stage_zero=stage_zero.model_dump(mode="json"),
                llm_triage=llm_triage.model_dump(mode="json"),
                detail_gate=detail_gate.model_dump(mode="json"),
                photo_review=photo_review,
                canonical_candidate=canonical.model_dump(mode="json"),
                market_check=market_check.model_dump(mode="json"),
                costs=costs,
            )
            if summary["rough_post_fee_gap"] and summary["rough_post_fee_gap"] > 0:
                counts["positive_gap_candidates"] += 1
            survivors.append(summary)
        finally:
            deep_tracker.advance(current_title=current_title, force=False)

    if deep_total == 0:
        print(
            json.dumps(
                {
                    "progress": {
                        "phase": "stage1_to_stage4",
                        "processed": 0,
                        "total": 0,
                        "percent_complete": 100.0,
                        "rate_per_minute": None,
                        "eta_minutes": None,
                        "current_title": None,
                    }
                }
            ),
            flush=True,
        )
    elif deep_tracker.processed < deep_total:
        deep_tracker.advance(current_title=None, force=True)

    survivors.sort(
        key=lambda item: (
            item["rough_post_fee_gap"] if item["rough_post_fee_gap"] is not None else -10**9,
            (item.get("market_check") or {}).get("confidence", 0.0),
        ),
        reverse=True,
    )

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "anchors": [search.label for search in selected_searches],
        "pages_per_anchor": pages_per_anchor,
        "max_stage0_accepts": max_stage0_accepts,
        "progress_every": progress_every,
        "fetched_pages": fetched_pages,
        "counts": counts,
        "usage": {
            "stage1": usage_summary(stage1_client.records),
            "stage3": usage_summary(stage3_client.records),
        },
        "survivors": survivors,
        "promising": [
            item
            for item in survivors
            if item["rough_post_fee_gap"] is not None and item["rough_post_fee_gap"] > 0
        ][:10],
    }

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"stack_smoke_{report_stamp}.json"
    report_path.write_text(json.dumps(report, indent=2))
    report["report_path"] = str(report_path)
    report["image_cache_dir"] = str(image_cache_dir)
    report["review_cache_dir"] = str(review_cache_dir)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--anchors",
        default="New York,Los Angeles",
        help="Comma-separated Craigslist anchor labels to scan.",
    )
    parser.add_argument(
        "--pages-per-anchor",
        type=int,
        default=1,
        help="How many result pages to fetch per anchor.",
    )
    parser.add_argument(
        "--report-dir",
        default="smoke_reports",
        help="Directory to store the JSON report and temporary image caches.",
    )
    parser.add_argument(
        "--max-stage0-accepts",
        type=int,
        default=None,
        help="Optional cap on how many Stage 0 survivors proceed deeper in the stack.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Emit progress after every N records during Stage 0 and deep processing.",
    )
    args = parser.parse_args()

    report = run_stack_smoke(
        anchor_labels=[part.strip() for part in args.anchors.split(",") if part.strip()],
        pages_per_anchor=args.pages_per_anchor,
        report_dir=Path(args.report_dir),
        max_stage0_accepts=args.max_stage0_accepts,
        progress_every=args.progress_every,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
