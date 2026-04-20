from __future__ import annotations

import re
from statistics import median

from scanner.libs.connectors.ebay import EbayConnector
from scanner.libs.nlp.text import normalize_text
from scanner.libs.schemas import (
    CanonicalAssetCandidate,
    MarketCheckComparable,
    MarketCheckResult,
    PhotoReviewResult,
    RawListingEvent,
)

TITLE_STOPWORDS = {
    "apple",
    "lenovo",
    "the",
    "with",
    "for",
    "and",
    "inch",
    "in",
    "computer",
}


class EbayMarketCheckService:
    def __init__(self, connector: EbayConnector) -> None:
        self.connector = connector

    def run(
        self,
        *,
        event: RawListingEvent,
        candidate: CanonicalAssetCandidate,
        photo_review: PhotoReviewResult,
    ) -> MarketCheckResult:
        query = self.build_query(event=event, candidate=candidate)
        page = self.connector.search(query=query, hydrate_details=False)

        matched: list[tuple[float, RawListingEvent]] = []
        for comparable in page.items:
            score = self._title_match_score(
                candidate=candidate,
                source_event=event,
                comparable_event=comparable,
            )
            if score >= 0.35:
                matched.append((score, comparable))

        matched.sort(key=lambda item: item[0], reverse=True)
        comparable_items = [
            MarketCheckComparable(
                source_listing_id=item.source_listing_id,
                title=item.title,
                listing_url=item.listing_url,
                total_price=round((item.price or 0.0) + (item.shipping_price or 0.0), 2),
                price=round(item.price or 0.0, 2),
                shipping_price=round(item.shipping_price or 0.0, 2),
                title_match_score=round(score, 3),
            )
            for score, item in matched[:10]
            if item.price is not None
        ]

        prices = [item.total_price for item in comparable_items]
        reasons = [
            "Used a targeted eBay Browse search as an active-listing market proxy.",
            f"Built query '{query}'.",
        ]
        if photo_review.confidence < 0.5:
            reasons.append(
                "Photo review confidence is limited, so market-check confidence is capped."
            )

        low = round(min(prices), 2) if prices else None
        median_price = round(float(median(prices)), 2) if prices else None
        high = round(max(prices), 2) if prices else None
        fast_sale = self._fast_sale_estimate(prices)

        confidence = 0.28
        confidence += min(candidate.confidence * 0.25, 0.25)
        confidence += 0.18 if len(comparable_items) >= 5 else 0.12 if comparable_items else 0.0
        if comparable_items:
            confidence += min(
                sum(item.title_match_score for item in comparable_items[:5])
                / min(len(comparable_items), 5)
                * 0.25,
                0.25,
            )
        confidence = min(confidence, photo_review.confidence + 0.15, 0.92)

        if not comparable_items:
            reasons.append("No close active eBay matches cleared the title-similarity threshold.")
        else:
            reasons.append(f"Retained {len(comparable_items)} close active eBay matches.")

        return MarketCheckResult(
            query=query,
            match_count=len(comparable_items),
            price_low=low,
            price_median=median_price,
            price_high=high,
            fast_sale_estimate=fast_sale,
            confidence=round(max(confidence, 0.1), 3),
            comparable_titles=[item.title for item in comparable_items[:5] if item.title],
            comparable_items=comparable_items,
            reasons=reasons,
        )

    def build_query(
        self,
        *,
        event: RawListingEvent,
        candidate: CanonicalAssetCandidate,
    ) -> str:
        source_text = normalize_text(event.title, event.description, event.model_text, event.brand)
        title_query = _clean_title_for_query(event.title or "")
        parts: list[str] = [title_query] if title_query else []

        for part in (candidate.brand, candidate.model, candidate.specs.cpu):
            if part and _phrase_supported_in_source(part, source_text):
                parts.append(part)

        if candidate.specs.ram_gb and f"{candidate.specs.ram_gb}gb" in source_text:
            parts.append(f"{candidate.specs.ram_gb}GB")
        if candidate.specs.storage_gb:
            storage = candidate.specs.storage_gb
            storage_text = (
                f"{storage // 1024}TB"
                if storage >= 1024 and storage % 1024 == 0
                else f"{storage}GB"
            )
            if storage_text.lower() in source_text:
                parts.append(storage_text)

        cleaned_parts = [part.strip() for part in parts if part and part.strip()]
        return " ".join(dict.fromkeys(cleaned_parts)).strip() or (event.title or "laptop")

    def _title_match_score(
        self,
        *,
        candidate: CanonicalAssetCandidate,
        source_event: RawListingEvent,
        comparable_event: RawListingEvent,
    ) -> float:
        source_text = normalize_text(source_event.title, source_event.description)
        if candidate.model and _phrase_supported_in_source(candidate.model, source_text):
            source_text = normalize_text(source_text, candidate.model)
        if candidate.brand and _phrase_supported_in_source(candidate.brand, source_text):
            source_text = normalize_text(source_text, candidate.brand)
        comparable_text = normalize_text(comparable_event.title, comparable_event.description)

        source_tokens = {
            token
            for token in source_text.split()
            if len(token) > 2 and token not in TITLE_STOPWORDS
        }
        comparable_tokens = {
            token
            for token in comparable_text.split()
            if len(token) > 2 and token not in TITLE_STOPWORDS
        }
        if not source_tokens or not comparable_tokens:
            return 0.0

        overlap = len(source_tokens & comparable_tokens)
        score = overlap / len(source_tokens)
        if candidate.model and normalize_text(candidate.model) in comparable_text:
            score += 0.2
        if candidate.brand and normalize_text(candidate.brand) in comparable_text:
            score += 0.1
        return min(score, 1.0)

    def _fast_sale_estimate(self, prices: list[float]) -> float | None:
        if not prices:
            return None
        ordered = sorted(prices)
        lower_quartile = ordered[max(0, round((len(ordered) - 1) * 0.25))]
        fast_sale = min(lower_quartile, median(ordered) * 0.94)
        return round(float(fast_sale), 2)


def _clean_title_for_query(title: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9+\"]+", title)
    cleaned = []
    for token in tokens:
        lowered = token.lower()
        if lowered in TITLE_STOPWORDS:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            continue
        cleaned.append(token)
    return " ".join(cleaned[:10]).strip()


def _phrase_supported_in_source(phrase: str, source_text: str) -> bool:
    normalized_phrase = normalize_text(phrase)
    if normalized_phrase in source_text:
        return True
    phrase_tokens = {token for token in normalized_phrase.split() if len(token) > 2}
    source_tokens = {token for token in source_text.split() if len(token) > 2}
    if not phrase_tokens:
        return False
    overlap = len(phrase_tokens & source_tokens)
    return overlap / len(phrase_tokens) >= 0.6
