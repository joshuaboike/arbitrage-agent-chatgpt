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
    "the",
    "with",
    "for",
    "and",
    "computer",
    "laptop",
    "sale",
    "excellent",
    "condition",
}
RELEVANT_NUMERIC_TOKENS = {
    "11",
    "12",
    "13",
    "14",
    "15",
    "16",
    "17",
    "18",
    "24",
    "32",
    "36",
    "40",
    "48",
    "64",
    "96",
    "128",
    "256",
    "512",
    "1024",
    "2048",
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
        query = self.build_query(
            event=event,
            candidate=candidate,
            photo_review=photo_review,
        )
        page = self.connector.search(query=query, hydrate_details=False)

        matched: list[tuple[float, RawListingEvent]] = []
        for comparable in page.items:
            score = self._title_match_score(
                source_event=event,
                photo_review=photo_review,
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

        confidence = 0.25
        if photo_review.extracted_facts.model_text:
            confidence += 0.16
        elif candidate.model:
            confidence += 0.08
        if comparable_items:
            confidence += 0.18 if len(comparable_items) >= 5 else 0.1
            confidence += min(
                sum(item.title_match_score for item in comparable_items[:5])
                / min(len(comparable_items), 5)
                * 0.28,
                0.28,
            )
        confidence = min(confidence, photo_review.confidence + 0.18, 0.92)

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
        photo_review: PhotoReviewResult,
    ) -> str:
        extracted = photo_review.extracted_facts
        parts: list[str] = []

        if extracted.model_text:
            parts.append(_clean_title_for_query(extracted.model_text))
        else:
            title_query = _clean_title_for_query(event.title or "")
            if title_query:
                parts.append(title_query)

        if extracted.cpu and extracted.cpu.lower() not in normalize_text(*parts):
            parts.append(extracted.cpu)
        if extracted.ram_gb:
            parts.append(f"{extracted.ram_gb}GB")
        elif candidate.specs.ram_gb and _value_supported_in_source(
            f"{candidate.specs.ram_gb}gb",
            event=event,
            photo_review=photo_review,
        ):
            parts.append(f"{candidate.specs.ram_gb}GB")

        storage_text = _storage_text(
            extracted.storage_gb or (
                candidate.specs.storage_gb
                if _storage_supported_in_source(
                    candidate.specs.storage_gb,
                    event=event,
                    photo_review=photo_review,
                )
                else None
            )
        )
        if storage_text:
            parts.append(storage_text)

        if extracted.brand and extracted.brand.lower() not in normalize_text(*parts):
            parts.insert(0, extracted.brand)
        elif candidate.brand and candidate.brand.lower() not in normalize_text(*parts):
            parts.insert(0, candidate.brand)

        cleaned_parts = [part.strip() for part in parts if part and part.strip()]
        return " ".join(dict.fromkeys(cleaned_parts)).strip() or (event.title or "laptop")

    def _title_match_score(
        self,
        *,
        source_event: RawListingEvent,
        photo_review: PhotoReviewResult,
        comparable_event: RawListingEvent,
    ) -> float:
        extracted = photo_review.extracted_facts
        source_text = normalize_text(
            source_event.title,
            extracted.model_text,
            extracted.family,
            extracted.brand,
            extracted.cpu,
            f"{extracted.ram_gb}gb" if extracted.ram_gb else None,
            _storage_text(extracted.storage_gb),
            extracted.screen_size,
            str(extracted.year) if extracted.year else None,
        )
        comparable_text = normalize_text(comparable_event.title, comparable_event.description)

        source_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", source_text)
            if _use_token_for_matching(token)
        }
        comparable_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", comparable_text)
            if _use_token_for_matching(token)
        }
        if not source_tokens or not comparable_tokens:
            return 0.0

        overlap = len(source_tokens & comparable_tokens)
        score = overlap / len(source_tokens)
        if extracted.model_text and normalize_text(extracted.model_text) in comparable_text:
            score += 0.2
        elif source_event.title and normalize_text(source_event.title) in comparable_text:
            score += 0.12
        if extracted.cpu and normalize_text(extracted.cpu) in comparable_text:
            score += 0.08
        if extracted.ram_gb and normalize_text(f"{extracted.ram_gb}gb") in comparable_text:
            score += 0.05
        storage_hint = _storage_text(extracted.storage_gb)
        if storage_hint and normalize_text(storage_hint) in comparable_text:
            score += 0.05
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
        if lowered.isdigit() and lowered not in RELEVANT_NUMERIC_TOKENS:
            continue
        cleaned.append(token)
    return " ".join(cleaned[:12]).strip()


def _use_token_for_matching(token: str) -> bool:
    if token in TITLE_STOPWORDS:
        return False
    if len(token) > 2:
        return True
    return token in RELEVANT_NUMERIC_TOKENS


def _storage_text(storage_gb: int | None) -> str | None:
    if not storage_gb:
        return None
    if storage_gb >= 1024 and storage_gb % 1024 == 0:
        return f"{storage_gb // 1024}TB"
    return f"{storage_gb}GB"


def _value_supported_in_source(
    value: str | None,
    *,
    event: RawListingEvent,
    photo_review: PhotoReviewResult,
) -> bool:
    if not value:
        return False
    source_text = normalize_text(
        event.title,
        event.description,
        photo_review.extracted_facts.ocr_text,
        photo_review.extracted_facts.model_text,
    )
    return normalize_text(value) in source_text


def _storage_supported_in_source(
    storage_gb: int | None,
    *,
    event: RawListingEvent,
    photo_review: PhotoReviewResult,
) -> bool:
    if not storage_gb:
        return False

    storage_text = _storage_text(storage_gb)
    if _value_supported_in_source(storage_text, event=event, photo_review=photo_review):
        return True

    raw_text = " ".join(
        part
        for part in [
            event.title or "",
            event.description or "",
            photo_review.extracted_facts.ocr_text or "",
            photo_review.extracted_facts.model_text or "",
        ]
        if part
    ).lower()

    if storage_gb >= 1024 and storage_gb % 1024 == 0:
        tb_value = storage_gb / 1024
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*tb\b", raw_text):
            observed_tb = float(match.group(1))
            if abs(observed_tb - tb_value) <= 0.15:
                return True

    for match in re.finditer(r"(\d{3,4})\s*gb\b", raw_text):
        observed_gb = int(match.group(1))
        if abs(observed_gb - storage_gb) <= 32:
            return True

    return False
