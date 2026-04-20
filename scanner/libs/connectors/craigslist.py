from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from urllib.parse import urlencode, urljoin

import httpx

from scanner.libs.schemas import CraigslistSearchDefinition, EventType, RawListingEvent
from scanner.libs.utils.config import CraigslistSettings

CARD_BLOCK_RE = re.compile(r'<li class="cl-static-search-result"[^>]*>(?P<body>.*?)</li>', re.S)
HREF_RE = re.compile(r'<a href="(?P<href>[^"]+)"')
TITLE_RE = re.compile(r'<div class="title">(?P<title>.*?)</div>', re.S)
PRICE_RE = re.compile(r'<div class="price">\$(?P<price>.*?)</div>', re.S)
LOCATION_RE = re.compile(r'<div class="location">\s*(?P<location>.*?)\s*</div>', re.S)
LISTING_ID_RE = re.compile(r"/(?P<listing_id>\d+)\.html(?:$|\?)")
DETAIL_TITLE_RE = re.compile(r'<span id="titletextonly">(?P<title>.*?)</span>', re.S)
DETAIL_BODY_RE = re.compile(r'<section id="postingbody"[^>]*>(?P<body>.*?)</section>', re.S)
DETAIL_ATTRGROUP_RE = re.compile(r'<p class="attrgroup"[^>]*>(?P<body>.*?)</p>', re.S)
DETAIL_IMAGE_RE = re.compile(r'(?:src|data-imgsrc)="(?P<url>https?://[^"]+)"')
DETAIL_MAPADDRESS_RE = re.compile(r'<div class="mapaddress">(?P<location>.*?)</div>', re.S)


class CraigslistConnector:
    source_id = "craigslist"

    def __init__(
        self,
        *,
        settings: CraigslistSettings,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
        )

    def build_anchor_searches(self) -> list[CraigslistSearchDefinition]:
        searches: list[CraigslistSearchDefinition] = []
        for anchor in self.settings.anchors:
            url = self.build_page_url(
                CraigslistSearchDefinition(
                    label=anchor.label,
                    site=anchor.site,
                    postal_code=anchor.postal_code,
                    search_distance=self.settings.search_distance,
                    category=self.settings.category,
                    delivery_available=self.settings.delivery_available,
                    query=self.settings.default_query,
                    url="",
                )
            )
            searches.append(
                CraigslistSearchDefinition(
                    label=anchor.label,
                    site=anchor.site,
                    postal_code=anchor.postal_code,
                    search_distance=self.settings.search_distance,
                    category=self.settings.category,
                    delivery_available=self.settings.delivery_available,
                    query=self.settings.default_query,
                    url=url,
                )
            )
        return searches

    def build_page_url(self, search: CraigslistSearchDefinition, *, offset: int = 0) -> str:
        query_params: dict[str, str | int] = {
            "delivery_available": 1 if search.delivery_available else 0,
            "postal": search.postal_code,
            "search_distance": search.search_distance,
            "query": search.query,
        }
        if offset > 0:
            query_params["s"] = offset
        return (
            f"https://{search.site}.craigslist.org/search/{search.category}?"
            f"{urlencode(query_params)}"
        )

    def fetch_page_html(self, url: str) -> str:
        response = self.client.get(url)
        response.raise_for_status()
        return response.text

    def fetch_detail_html(self, listing_url: str) -> str:
        response = self.client.get(listing_url)
        response.raise_for_status()
        return response.text

    def fetch_result_cards(
        self,
        search: CraigslistSearchDefinition,
        *,
        offset: int = 0,
        observed_at: datetime | None = None,
    ) -> list[RawListingEvent]:
        page_url = self.build_page_url(search, offset=offset)
        html_content = self.fetch_page_html(page_url)
        return self.parse_result_cards(
            html_content,
            page_url=page_url,
            source_label=search.label,
            observed_at=observed_at,
        )

    def parse_result_cards(
        self,
        html_content: str,
        *,
        page_url: str,
        source_label: str,
        observed_at: datetime | None = None,
    ) -> list[RawListingEvent]:
        records: list[RawListingEvent] = []
        seen_listing_ids: set[str] = set()
        timestamp = observed_at or datetime.now(UTC)

        for match in CARD_BLOCK_RE.finditer(html_content):
            body = match.group("body")
            href_match = HREF_RE.search(body)
            title_match = TITLE_RE.search(body)
            if href_match is None or title_match is None:
                continue

            listing_url = urljoin(page_url, html.unescape(href_match.group("href")))
            listing_id_match = LISTING_ID_RE.search(listing_url)
            if listing_id_match is None:
                continue
            listing_id = listing_id_match.group("listing_id")
            if listing_id in seen_listing_ids:
                continue
            seen_listing_ids.add(listing_id)

            title = html.unescape(_strip_tags(title_match.group("title"))).strip()
            price_value = _parse_price(PRICE_RE.search(body))
            location = _parse_location(LOCATION_RE.search(body))

            records.append(
                RawListingEvent(
                    event_id=f"craigslist:{listing_id}:{int(timestamp.timestamp())}",
                    source="craigslist",
                    source_listing_id=listing_id,
                    event_type=EventType.CREATE,
                    observed_at=timestamp,
                    listing_url=listing_url,
                    title=title or None,
                    description=None,
                    price=price_value,
                    currency="USD",
                    shipping_price=None,
                    shipping_type="unknown",
                    location_text=location,
                    images=[],
                    category_path=["for sale", "computers"],
                    attributes={
                        "anchor_label": source_label,
                        "search_page_url": page_url,
                    },
                    raw_payload={
                        "page_url": page_url,
                        "source_label": source_label,
                    },
                )
            )

        return records

    def hydrate_listing_detail(
        self,
        event: RawListingEvent,
        *,
        observed_at: datetime | None = None,
    ) -> RawListingEvent:
        if not event.listing_url:
            raise ValueError("Craigslist detail hydration requires a listing URL.")
        html_content = self.fetch_detail_html(event.listing_url)
        return self.parse_detail_page(
            html_content,
            seed_event=event,
            observed_at=observed_at,
        )

    def parse_detail_page(
        self,
        html_content: str,
        *,
        seed_event: RawListingEvent,
        observed_at: datetime | None = None,
    ) -> RawListingEvent:
        detail_title = _extract_first_group(DETAIL_TITLE_RE, html_content, "title")
        detail_body = _extract_first_group(DETAIL_BODY_RE, html_content, "body")
        detail_location = _extract_first_group(DETAIL_MAPADDRESS_RE, html_content, "location")

        attr_texts = [
            cleaned
            for match in DETAIL_ATTRGROUP_RE.finditer(html_content)
            for cleaned in _split_attrgroup_text(match.group("body"))
            if cleaned
        ]
        page_text_parts = [detail_body, *attr_texts]
        page_text = " ".join(part for part in page_text_parts if part)
        image_urls = list(
            dict.fromkeys(
                [
                    *seed_event.images,
                    *[
                        html.unescape(match.group("url"))
                        for match in DETAIL_IMAGE_RE.finditer(html_content)
                    ],
                ]
            )
        )

        shipping_type, availability_status = _derive_fulfillment_signals(page_text)
        detail_payload = {
            **seed_event.raw_payload,
            "detail_attributes": attr_texts,
            "detail_page_excerpt": page_text[:4000],
        }

        hydrated_at = observed_at or datetime.now(UTC)

        return seed_event.model_copy(
            update={
                "event_id": (
                    f"{seed_event.source_listing_id}:detail:{int(hydrated_at.timestamp())}"
                ),
                "observed_at": hydrated_at,
                "title": detail_title or seed_event.title,
                "description": detail_body or seed_event.description,
                "location_text": detail_location or seed_event.location_text,
                "images": image_urls,
                "shipping_type": shipping_type or seed_event.shipping_type,
                "availability_status": availability_status or seed_event.availability_status,
                "attributes": {
                    **seed_event.attributes,
                    "detail_attributes": attr_texts,
                },
                "raw_payload": detail_payload,
            }
        )


def _parse_price(match: re.Match[str] | None) -> float | None:
    if match is None:
        return None
    price_text = html.unescape(_strip_tags(match.group("price")))
    normalized = price_text.replace(",", "")
    normalized = "".join(
        character for character in normalized if character.isdigit() or character == "."
    )
    normalized = normalized.strip()
    if not normalized:
        return None
    return float(normalized)


def _parse_location(match: re.Match[str] | None) -> str | None:
    if match is None:
        return None
    location = html.unescape(_strip_tags(match.group("location"))).strip()
    return location or None


def _extract_first_group(pattern: re.Pattern[str], value: str, group_name: str) -> str | None:
    match = pattern.search(value)
    if match is None:
        return None
    cleaned = _clean_detail_text(match.group(group_name))
    return cleaned or None


def _split_attrgroup_text(value: str) -> list[str]:
    parts = re.findall(r"<span[^>]*>(.*?)</span>", value, re.S)
    if not parts:
        cleaned = _clean_detail_text(value)
        return [cleaned] if cleaned else []
    return [cleaned for part in parts if (cleaned := _clean_detail_text(part))]


def _clean_detail_text(value: str) -> str:
    cleaned = html.unescape(_strip_tags(value))
    cleaned = cleaned.replace("QR Code Link to This Post", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _derive_fulfillment_signals(page_text: str) -> tuple[str | None, str | None]:
    normalized = " ".join(page_text.lower().split())
    if not normalized:
        return None, None
    if "pickup only" in normalized or "local pickup only" in normalized:
        return "pickup_only", "pickup_only"
    if "delivery available" in normalized or "shipping available" in normalized:
        return "shipping_available", "delivery_available"
    if "will ship" in normalized or "ships" in normalized:
        return "shipping_available", "shipping_available"
    return None, None


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)
