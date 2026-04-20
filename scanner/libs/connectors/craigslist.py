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


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)
