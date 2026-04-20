from __future__ import annotations

import re

from scanner.libs.schemas import LotAnalysis, LotComponentCandidate, RawListingEvent

LOT_SIGNALS = (
    "bundle",
    "lot",
    "plus",
    "with",
    "&",
    "/",
)
COMPONENT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("macbook pro", "MacBook Pro"),
    ("macbook air", "MacBook Air"),
    ("mac mini", "Mac mini"),
    ("thinkpad", "ThinkPad"),
    ("xps", "Dell XPS"),
    ("latitude", "Dell Latitude"),
    ("elitebook", "HP EliteBook"),
    ("zenbook", "ASUS Zenbook"),
    ("spectre", "HP Spectre"),
    ("surface laptop", "Surface Laptop"),
    ("chromebook", "Chromebook"),
)


def _normalized_listing_text(event: RawListingEvent) -> str:
    parts = [event.title or "", event.description or ""]
    return " ".join(" ".join(parts).lower().split())


class LotAnalyzer:
    def analyze(self, event: RawListingEvent) -> LotAnalysis:
        haystack = _normalized_listing_text(event)
        candidates: list[LotComponentCandidate] = []
        reasons: list[str] = []

        for pattern, label in COMPONENT_PATTERNS:
            if pattern in haystack:
                quantity_hint = self._quantity_hint(haystack, pattern)
                candidates.append(
                    LotComponentCandidate(
                        item_type="computer",
                        label=label,
                        quantity_hint=quantity_hint,
                        confidence=0.7 if quantity_hint > 1 else 0.6,
                        reasons=[f"Matched component token '{pattern}'."],
                    )
                )

        signal_count = sum(1 for signal in LOT_SIGNALS if signal in haystack)
        if signal_count:
            reasons.append("Listing text contains bundle or multi-item signals.")
        if len(candidates) > 1:
            reasons.append("Multiple device families were detected in one listing.")
        if sum(candidate.quantity_hint for candidate in candidates) > 1:
            reasons.append("Quantity hints imply more than one resalable unit.")

        is_multi_item = bool(
            signal_count or len(candidates) > 1 or sum(c.quantity_hint for c in candidates) > 1
        )
        return LotAnalysis(
            is_multi_item=is_multi_item,
            should_split_valuation=is_multi_item,
            confidence=0.82 if is_multi_item else 0.45,
            reasons=reasons or ["No strong multi-item signals detected."],
            component_candidates=candidates,
        )

    def _quantity_hint(self, text: str, pattern: str) -> int:
        explicit_quantity = re.search(rf"\b(\d+)\s+{re.escape(pattern)}\b", text)
        if explicit_quantity:
            return max(int(explicit_quantity.group(1)), 1)
        return 1
