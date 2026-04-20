from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query

from scanner.libs.schemas import IngestTestListingRequest
from scanner.libs.services.container import ApplicationContainer
from scanner.libs.storage.repositories import ListingRepository, UnderwritingRepository

container = ApplicationContainer()
app = FastAPI(title="scanner API", version="0.1.0")


def get_container() -> ApplicationContainer:
    return container


@app.get("/health")
def health(current_container: ApplicationContainer = Depends(get_container)) -> dict:
    return {
        "status": "ok",
        "environment": current_container.settings.app_env,
        "metrics": current_container.metrics.snapshot(),
    }


@app.get("/alerts/recent")
def recent_alerts(current_container: ApplicationContainer = Depends(get_container)) -> list[dict]:
    with current_container.session_scope() as session:
        repository = UnderwritingRepository(session)
        alerts = repository.recent_alerts()
        return [alert.model_dump(mode="json") for alert in alerts]


@app.get("/sources/ebay/search")
def search_ebay(
    q: str = Query(..., min_length=2),
    hydrate_details: bool = Query(default=True),
    current_container: ApplicationContainer = Depends(get_container),
) -> dict:
    connector = current_container.connector_registry.create("ebay")
    try:
        page = connector.search(query=q, hydrate_details=hydrate_details)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "items": [item.model_dump(mode="json") for item in page.items],
        "next_cursor": page.next_cursor.model_dump(mode="json") if page.next_cursor else None,
    }


@app.get("/listings/{listing_id}")
def get_listing(
    listing_id: str, current_container: ApplicationContainer = Depends(get_container)
) -> dict:
    with current_container.session_scope() as session:
        repository = ListingRepository(session)
        listing = repository.get(listing_id)
        if listing is None:
            raise HTTPException(status_code=404, detail="Listing not found.")
        return {
            "listing_pk": listing.listing_pk,
            "source": listing.source,
            "source_listing_id": listing.source_listing_id,
            "title": listing.title,
            "description": listing.description,
            "price": listing.price,
            "shipping_price": listing.shipping_price,
            "currency": listing.currency,
            "seller_id": listing.seller_id,
            "status": listing.status,
            "listing_url": listing.listing_url,
            "first_seen_at": listing.first_seen_at.isoformat(),
            "last_seen_at": listing.last_seen_at.isoformat(),
        }


@app.get("/underwriting/{listing_id}")
def get_underwriting(
    listing_id: str, current_container: ApplicationContainer = Depends(get_container)
) -> dict:
    with current_container.session_scope() as session:
        repository = UnderwritingRepository(session)
        result = repository.get(listing_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Underwriting result not found.")
        return result.model_dump(mode="json")


@app.post("/listings/test-ingest")
def ingest_test_listing(
    request: IngestTestListingRequest,
    current_container: ApplicationContainer = Depends(get_container),
) -> dict:
    with current_container.session_scope() as session:
        pipeline = current_container.pipeline(session)
        event = pipeline.build_raw_event(request)
        listing = pipeline.ingest(event)
        result = pipeline.underwrite(listing.listing_pk)
        return {
            "listing_pk": listing.listing_pk,
            "underwriting": result.model_dump(mode="json"),
        }
