from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import quote
from uuid import uuid4

import httpx

from scanner.libs.connectors.base import ConnectorCursor, ListingPage
from scanner.libs.schemas import EventType, RawListingEvent
from scanner.libs.utils.config import EbaySettings


def _extract_image_urls(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    if image_url := payload.get("image", {}).get("imageUrl"):
        urls.append(image_url)

    product = payload.get("product", {})
    if image_url := product.get("image", {}).get("imageUrl"):
        urls.append(image_url)
    additional_images = product.get("additionalImages", [])
    urls.extend(
        image.get("imageUrl")
        for image in additional_images
        if isinstance(image, dict) and image.get("imageUrl")
    )

    urls.extend(
        image.get("imageUrl")
        for image in payload.get("additionalImages", [])
        if isinstance(image, dict) and image.get("imageUrl")
    )

    return list(dict.fromkeys(urls))


def _extract_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    localized_aspects = payload.get("localizedAspects", [])
    attributes = {
        item.get("name"): item.get("value") for item in localized_aspects if item.get("name")
    }

    product = payload.get("product", {})
    if product.get("brand"):
        attributes.setdefault("Brand", product["brand"])
    if product.get("title"):
        attributes.setdefault("ProductTitle", product["title"])

    return attributes


def _extract_category_path(payload: dict[str, Any]) -> list[str]:
    categories = payload.get("categories", [])
    if categories:
        return [
            category.get("categoryName")
            for category in categories
            if category.get("categoryName")
        ]

    if category_path := payload.get("categoryPath"):
        return [part.strip() for part in category_path.split(",") if part.strip()]

    return []


def _extract_location(payload: dict[str, Any]) -> str | None:
    item_location = payload.get("itemLocation", {})
    location_parts = [
        item_location.get("city"),
        item_location.get("stateOrProvince"),
        item_location.get("country"),
    ]
    filtered = [part for part in location_parts if part]
    if filtered:
        return ", ".join(filtered)
    return None


def _extract_availability(payload: dict[str, Any]) -> str | None:
    if payload.get("availabilityStatus"):
        return payload["availabilityStatus"]

    estimated = payload.get("estimatedAvailabilities") or []
    if estimated and isinstance(estimated[0], dict):
        return estimated[0].get("availabilityStatus")

    return None


def _extract_quantity(payload: dict[str, Any]) -> int | None:
    quantity = payload.get("quantity")
    if quantity is not None:
        return quantity

    estimated = payload.get("estimatedAvailabilities") or []
    if estimated and isinstance(estimated[0], dict):
        return estimated[0].get("estimatedAvailableQuantity")

    return None


@dataclass
class OAuthToken:
    access_token: str
    expires_at: datetime
    token_type: str = "Bearer"

    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at


class EbayBrowseProvider(Protocol):
    def search(
        self,
        *,
        query: str,
        page_size: int,
        cursor: ConnectorCursor | None = None,
    ) -> dict[str, Any]: ...

    def get_item(
        self,
        *,
        item_id: str,
        fieldgroups: tuple[str, ...],
    ) -> dict[str, Any]: ...


class EbayOAuthTokenProvider:
    def __init__(self, settings: EbaySettings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.request_timeout_seconds)
        self._cached_token: OAuthToken | None = None

    def get_token(self) -> str:
        if self.settings.oauth_token:
            return self.settings.oauth_token

        if self._cached_token and not self._cached_token.is_expired():
            return self._cached_token.access_token

        if not self.settings.client_id or not self.settings.client_secret:
            raise RuntimeError(
                "eBay Browse access requires either EBAY_OAUTH_TOKEN or both "
                "EBAY_CLIENT_ID and EBAY_CLIENT_SECRET."
            )

        credentials = f"{self.settings.client_id}:{self.settings.client_secret}".encode()
        encoded_credentials = base64.b64encode(credentials).decode()
        response = self.client.post(
            f"{self.settings.identity_base_url}/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {encoded_credentials}",
            },
            data={
                "grant_type": "client_credentials",
                "scope": " ".join(self.settings.oauth_scopes),
            },
        )
        response.raise_for_status()
        payload = response.json()

        expires_at = datetime.now(UTC) + timedelta(seconds=max(payload["expires_in"] - 60, 60))
        self._cached_token = OAuthToken(
            access_token=payload["access_token"],
            expires_at=expires_at,
            token_type=payload.get("token_type", "Bearer"),
        )
        return self._cached_token.access_token


class HttpEbayBrowseProvider:
    def __init__(
        self,
        settings: EbaySettings,
        *,
        token_provider: EbayOAuthTokenProvider | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.request_timeout_seconds)
        self.token_provider = token_provider or EbayOAuthTokenProvider(settings, client=self.client)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token_provider.get_token()}",
            "X-EBAY-C-MARKETPLACE-ID": self.settings.site_id,
        }
        if self.settings.end_user_context:
            headers["X-EBAY-C-ENDUSERCTX"] = self.settings.end_user_context
        return headers

    def search(
        self,
        *,
        query: str,
        page_size: int,
        cursor: ConnectorCursor | None = None,
    ) -> dict[str, Any]:
        if cursor and cursor.continuation_token:
            response = self.client.get(
                cursor.continuation_token,
                headers=self._headers(),
            )
        else:
            response = self.client.get(
                f"{self.settings.browse_base_url}/item_summary/search",
                headers=self._headers(),
                params={
                    "q": query,
                    "limit": page_size,
                },
            )

        response.raise_for_status()
        return response.json()

    def get_item(
        self,
        *,
        item_id: str,
        fieldgroups: tuple[str, ...],
    ) -> dict[str, Any]:
        encoded_item_id = quote(item_id, safe="|")
        params: dict[str, str] = {}
        if fieldgroups:
            params["fieldgroups"] = ",".join(fieldgroups)

        response = self.client.get(
            f"{self.settings.browse_base_url}/item/{encoded_item_id}",
            headers=self._headers(),
            params=params,
        )
        response.raise_for_status()
        return response.json()


class StubEbayBrowseProvider:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        item_details_by_id: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.payload = payload
        self.item_details_by_id = item_details_by_id or {}

    def search(
        self,
        *,
        query: str,
        page_size: int,
        cursor: ConnectorCursor | None = None,
    ) -> dict[str, Any]:
        return self.payload

    def get_item(
        self,
        *,
        item_id: str,
        fieldgroups: tuple[str, ...],
    ) -> dict[str, Any]:
        return self.item_details_by_id[item_id]


class UnavailableEbayBrowseProvider:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def search(
        self,
        *,
        query: str,
        page_size: int,
        cursor: ConnectorCursor | None = None,
    ) -> dict[str, Any]:
        raise RuntimeError(self.reason)

    def get_item(
        self,
        *,
        item_id: str,
        fieldgroups: tuple[str, ...],
    ) -> dict[str, Any]:
        raise RuntimeError(self.reason)


class EbayConnector:
    source_id = "ebay"

    def __init__(self, provider: EbayBrowseProvider, settings: EbaySettings) -> None:
        self.provider = provider
        self.settings = settings

    def search(
        self,
        *,
        query: str,
        cursor: ConnectorCursor | None = None,
        hydrate_details: bool = False,
    ) -> ListingPage:
        response = self.provider.search(
            query=query,
            page_size=self.settings.page_size,
            cursor=cursor,
        )
        item_summaries = response.get("itemSummaries", [])
        items: list[RawListingEvent] = []

        for item_summary in item_summaries:
            item_details = None
            if hydrate_details and item_summary.get("itemId"):
                item_details = self.provider.get_item(
                    item_id=item_summary["itemId"],
                    fieldgroups=self.settings.detail_fieldgroups,
                )

            items.append(
                self.normalize_item_summary(
                    item_summary,
                    item_details=item_details,
                )
            )

        next_cursor = None
        if response.get("next"):
            next_cursor = ConnectorCursor(
                continuation_token=response["next"],
                page_number=(cursor.page_number + 1) if cursor else 2,
            )
        return ListingPage(items=items, next_cursor=next_cursor)

    def normalize_item_summary(
        self,
        item_summary: dict[str, Any],
        *,
        item_details: dict[str, Any] | None = None,
    ) -> RawListingEvent:
        payload = item_details or item_summary
        shipping_options = payload.get("shippingOptions") or item_summary.get("shippingOptions", [])
        shipping_price = 0.0
        shipping_type = None
        if shipping_options:
            first_shipping = shipping_options[0]
            shipping_type = first_shipping.get("shippingCostType")
            shipping_cost = first_shipping.get("shippingCost", {})
            shipping_price = float(shipping_cost.get("value", 0.0))

        images = _extract_image_urls(item_summary)
        if item_details:
            images = list(dict.fromkeys(images + _extract_image_urls(item_details)))

        attributes = _extract_attributes(item_summary)
        if item_details:
            attributes.update(_extract_attributes(item_details))

        seller = item_summary.get("seller", {})
        if item_details:
            seller = {**seller, **item_details.get("seller", {})}

        description = payload.get("description") or item_summary.get("shortDescription")
        if payload.get("conditionDescription"):
            description = "\n\n".join(
                part for part in [description, payload.get("conditionDescription")] if part
            )

        category_path = _extract_category_path(payload)
        location_text = _extract_location(payload) or _extract_location(item_summary)

        return RawListingEvent(
            event_id=str(uuid4()),
            source=self.source_id,
            source_listing_id=item_summary["itemId"],
            event_type=EventType.CREATE,
            observed_at=datetime.now(UTC),
            listing_url=payload.get("itemWebUrl") or item_summary.get("itemWebUrl"),
            seller_id=seller.get("username") or seller.get("userId"),
            title=payload.get("title") or item_summary.get("title"),
            description=description,
            price=float(payload.get("price", {}).get("value", 0.0)),
            currency=payload.get("price", {}).get("currency", "USD"),
            shipping_price=shipping_price,
            shipping_type=shipping_type,
            location_text=location_text,
            images=images,
            category_path=category_path,
            brand=attributes.get("Brand"),
            model_text=attributes.get("Model"),
            condition_text=payload.get("conditionDescription") or payload.get("condition"),
            attributes=attributes,
            availability_status=_extract_availability(payload),
            quantity=_extract_quantity(payload),
            seller_metadata=seller,
            raw_payload={
                "summary": item_summary,
                "details": item_details,
            }
            if item_details
            else item_summary,
        )
