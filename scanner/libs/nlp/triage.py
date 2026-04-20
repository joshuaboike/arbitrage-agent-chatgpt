from __future__ import annotations

import re

from scanner.libs.schemas import (
    DetailGateDecision,
    FulfillmentStatus,
    RawListingEvent,
    TriageDecision,
)

NEGATIVE_TITLE_PATTERNS = (
    "wanted",
    "repair",
    "service",
    "parts",
    "trade",
    "lease",
    "financing",
)
DEVICE_TOKENS = (
    "laptop",
    "notebook",
    "ultrabook",
    "macbook",
    "thinkpad",
    "xps",
    "latitude",
    "elitebook",
    "zenbook",
    "spectre",
    "surface laptop",
    "chromebook",
    "mac mini",
)

SHIPPABLE_PATTERNS = (
    "delivery available",
    "shipping available",
    "ships",
    "will ship",
)
PICKUP_ONLY_PATTERNS = (
    "pickup only",
    "local pickup only",
    "pick up only",
    "must pick up",
    "cash and carry",
)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.lower().split())


class StageZeroTriageService:
    def evaluate(self, event: RawListingEvent) -> TriageDecision:
        normalized_title = _normalize_text(event.title)
        reasons: list[str] = []

        if not event.title or not event.listing_url:
            return TriageDecision(
                accepted=False,
                normalized_title=normalized_title or None,
                reject_reason="missing_title_or_url",
                reasons=["Listing must have both title and URL before deeper review."],
            )

        if event.price is None or event.price < 80 or event.price > 2500:
            return TriageDecision(
                accepted=False,
                normalized_title=normalized_title,
                reject_reason="price_out_of_bounds",
                reasons=["Listing price is outside the v1 target range."],
            )

        for pattern in NEGATIVE_TITLE_PATTERNS:
            if re.search(rf"\b{re.escape(pattern)}\b", normalized_title):
                return TriageDecision(
                    accepted=False,
                    normalized_title=normalized_title,
                    reject_reason=f"title_negative:{pattern}",
                    reasons=[f"Title contains excluded token '{pattern}'."],
                )

        if not any(token in normalized_title for token in DEVICE_TOKENS):
            return TriageDecision(
                accepted=False,
                normalized_title=normalized_title,
                reject_reason="missing_device_token",
                reasons=["Title does not look like an in-scope laptop or Mac mini listing."],
            )

        reasons.append("Title passed deterministic v1 device and price filters.")
        return TriageDecision(
            accepted=True,
            normalized_title=normalized_title,
            reasons=reasons,
        )


class CraigslistDetailGateService:
    def evaluate(self, event: RawListingEvent) -> DetailGateDecision:
        haystack = " ".join(
            filter(
                None,
                (
                    _normalize_text(event.description),
                    _normalize_text(event.shipping_type),
                    _normalize_text(event.availability_status),
                    _normalize_text(str(event.attributes)),
                    _normalize_text(str(event.raw_payload)),
                ),
            )
        )

        if any(pattern in haystack for pattern in SHIPPABLE_PATTERNS):
            return DetailGateDecision(
                should_download_photos=True,
                fulfillment_status=FulfillmentStatus.SHIPPABLE,
                reasons=["Listing appears shippable or delivery-enabled."],
            )

        if any(pattern in haystack for pattern in PICKUP_ONLY_PATTERNS):
            return DetailGateDecision(
                should_download_photos=False,
                fulfillment_status=FulfillmentStatus.PICKUP_ONLY,
                exclusion_reason="pickup_only",
                reasons=["Listing is pickup only, which is a hard v1 exclusion."],
            )

        return DetailGateDecision(
            should_download_photos=False,
            fulfillment_status=FulfillmentStatus.UNKNOWN,
            exclusion_reason="fulfillment_unknown",
            reasons=["Fulfillment signal is unclear, so the listing does not advance."],
        )
