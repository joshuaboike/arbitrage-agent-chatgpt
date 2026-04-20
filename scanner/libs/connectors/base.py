from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from scanner.libs.schemas import RawListingEvent


class ConnectorCursor(BaseModel):
    continuation_token: str | None = None
    page_number: int = 1
    metadata: dict[str, str] = Field(default_factory=dict)


class ListingPage(BaseModel):
    items: list[RawListingEvent]
    next_cursor: ConnectorCursor | None = None


class SourceConnector(Protocol):
    source_id: str

    def search(
        self,
        *,
        query: str,
        cursor: ConnectorCursor | None = None,
        hydrate_details: bool = False,
    ) -> ListingPage: ...
