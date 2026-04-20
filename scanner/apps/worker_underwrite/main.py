from __future__ import annotations

from scanner.libs.events.bus import Topics
from scanner.libs.services.container import ApplicationContainer
from scanner.libs.utils.logging import get_logger

logger = get_logger(__name__)


def run_once() -> int:
    container = ApplicationContainer()
    messages = container.bus.consume(Topics.NORMALIZED_LISTING_EVENTS)
    processed = 0
    with container.session_scope() as session:
        pipeline = container.pipeline(session)
        for message in messages:
            listing_pk = message.payload["listing_pk"]
            pipeline.underwrite(listing_pk)
            processed += 1
    logger.info("worker_underwrite.completed", processed=processed)
    return processed


if __name__ == "__main__":
    run_once()
