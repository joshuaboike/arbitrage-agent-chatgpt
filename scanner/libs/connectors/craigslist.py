from __future__ import annotations

from urllib.parse import urlencode

from scanner.libs.schemas import CraigslistSearchDefinition
from scanner.libs.utils.config import CraigslistSettings


class CraigslistConnector:
    source_id = "craigslist"

    def __init__(self, *, settings: CraigslistSettings) -> None:
        self.settings = settings

    def build_anchor_searches(self) -> list[CraigslistSearchDefinition]:
        searches: list[CraigslistSearchDefinition] = []
        for anchor in self.settings.anchors:
            query_params = {
                "delivery_available": 1 if self.settings.delivery_available else 0,
                "postal": anchor.postal_code,
                "search_distance": self.settings.search_distance,
                "query": self.settings.default_query,
            }
            url = (
                f"https://{anchor.site}.craigslist.org/search/{self.settings.category}?"
                f"{urlencode(query_params)}"
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
