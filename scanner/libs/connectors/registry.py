from __future__ import annotations

from collections.abc import Callable

from scanner.libs.connectors.craigslist import CraigslistConnector
from scanner.libs.connectors.ebay import (
    EbayBrowseProvider,
    EbayConnector,
    HttpEbayBrowseProvider,
    UnavailableEbayBrowseProvider,
)
from scanner.libs.utils.config import CraigslistSettings, EbaySettings

ConnectorBuilder = Callable[[], object]


class ConnectorRegistry:
    def __init__(self) -> None:
        self._builders: dict[str, ConnectorBuilder] = {}

    def register(self, source_id: str, builder: ConnectorBuilder) -> None:
        self._builders[source_id] = builder

    def create(self, source_id: str) -> object:
        try:
            return self._builders[source_id]()
        except KeyError as exc:
            raise ValueError(f"No connector registered for source '{source_id}'.") from exc


def build_default_registry(
    *,
    ebay_provider: EbayBrowseProvider | None = None,
    ebay_settings: EbaySettings,
    craigslist_settings: CraigslistSettings,
) -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(
        "craigslist",
        lambda: CraigslistConnector(settings=craigslist_settings),
    )
    registry.register(
        "ebay",
        lambda: EbayConnector(
            provider=ebay_provider
            or (
                HttpEbayBrowseProvider(settings=ebay_settings)
                if ebay_settings.has_application_token_material
                else UnavailableEbayBrowseProvider(
                    "eBay connector is not configured. Set EBAY_CLIENT_ID and "
                    "EBAY_CLIENT_SECRET, or provide EBAY_OAUTH_TOKEN."
                )
            ),
            settings=ebay_settings,
        ),
    )
    return registry
