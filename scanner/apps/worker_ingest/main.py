from __future__ import annotations

import os

from scanner.libs.connectors.base import ConnectorCursor
from scanner.libs.events.bus import Topics
from scanner.libs.services.container import ApplicationContainer
from scanner.libs.utils.logging import get_logger

logger = get_logger(__name__)


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def run_once(query: str = "iphone 15 pro", *, hydrate_details: bool = True) -> int:
    container = ApplicationContainer()
    connector = container.connector_registry.create("ebay")
    page = connector.search(
        query=query,
        cursor=ConnectorCursor(),
        hydrate_details=hydrate_details,
    )
    for item in page.items:
        container.bus.publish(
            Topics.RAW_LISTING_EVENTS, item.model_dump(mode="json"), key=item.source_listing_id
        )
    logger.info(
        "worker_ingest.completed",
        query=query,
        hydrate_details=hydrate_details,
        ingested=len(page.items),
    )
    return len(page.items)


if __name__ == "__main__":
    run_once(
        query=os.getenv("EBAY_QUERY", "iphone 15 pro"),
        hydrate_details=_read_bool("EBAY_HYDRATE_DETAILS", True),
    )
