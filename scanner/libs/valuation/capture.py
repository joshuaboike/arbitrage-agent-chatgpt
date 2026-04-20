from __future__ import annotations

from scanner.libs.nlp.text import normalize_text
from scanner.libs.schemas import CaptureEstimate, RawListingEvent


class CaptureModel:
    def estimate(self, event: RawListingEvent, spread_ratio: float) -> CaptureEstimate:
        text = normalize_text(event.title, event.description)
        urgency_bonus = (
            0.12
            if any(term in text for term in ["must sell", "today", "obo", "need gone"])
            else 0.0
        )
        reply_probability = 0.58 + urgency_bonus
        ask_accept_probability = 0.62 + min(spread_ratio * 0.6, 0.22)
        close_probability = 0.78 if (event.shipping_type or "").lower() != "pickup" else 0.7
        listing_survival_probability = max(0.35, 0.85 - min(spread_ratio * 0.5, 0.35))
        local_pickup_success_probability = (
            0.82 if "pickup" in (event.shipping_type or "").lower() else 0.92
        )
        overall = (
            reply_probability
            * ask_accept_probability
            * close_probability
            * listing_survival_probability
            * local_pickup_success_probability
        )

        return CaptureEstimate(
            listing_survival_probability=round(min(listing_survival_probability, 0.95), 3),
            reply_probability=round(min(reply_probability, 0.95), 3),
            ask_accept_probability=round(min(ask_accept_probability, 0.95), 3),
            close_probability=round(min(close_probability, 0.95), 3),
            local_pickup_success_probability=round(min(local_pickup_success_probability, 0.95), 3),
            overall_capture_probability=round(min(overall, 0.95), 3),
            reasons=[
                "Applied heuristic capture model using urgency language and spread magnitude.",
            ],
        )
