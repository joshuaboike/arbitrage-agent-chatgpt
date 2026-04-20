from __future__ import annotations

from scanner.libs.events.bus import Topics
from scanner.libs.schemas import RawListingEvent
from scanner.libs.services.container import ApplicationContainer
from scanner.libs.utils.logging import get_logger

logger = get_logger(__name__)


def run_once() -> int:
    container = ApplicationContainer()
    messages = container.bus.consume(Topics.RAW_LISTING_EVENTS)
    processed = 0
    with container.session_scope() as session:
        pipeline = container.pipeline(session)
        for message in messages:
            event = RawListingEvent.model_validate(message.payload)
            pipeline.ingest(event)
            processed += 1
    logger.info("worker_normalize.completed", processed=processed)
    return processed


if __name__ == "__main__":
    run_once()
