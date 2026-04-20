from __future__ import annotations

from scanner.libs.events.bus import Topics
from scanner.libs.schemas import AlertPayload
from scanner.libs.services.alerts import GenericWebhookFormatter, SlackWebhookFormatter
from scanner.libs.services.container import ApplicationContainer
from scanner.libs.utils.logging import get_logger

logger = get_logger(__name__)


def run_once() -> int:
    container = ApplicationContainer()
    messages = container.bus.consume(Topics.ALERTS)
    slack = SlackWebhookFormatter()
    generic = GenericWebhookFormatter()
    processed = 0
    for message in messages:
        alert = AlertPayload.model_validate(message.payload)
        logger.info(
            "worker_alerts.alert_ready",
            slack_payload=slack.format(alert),
            generic_payload=generic.format(alert),
        )
        processed += 1
    logger.info("worker_alerts.completed", processed=processed)
    return processed


if __name__ == "__main__":
    run_once()
