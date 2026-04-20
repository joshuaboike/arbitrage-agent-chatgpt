from __future__ import annotations

from collections import defaultdict, deque
from typing import Protocol

from scanner.libs.schemas import EventEnvelope


class EventBus(Protocol):
    def publish(self, topic: str, payload: dict, key: str | None = None) -> EventEnvelope: ...

    def consume(self, topic: str, limit: int = 100) -> list[EventEnvelope]: ...


class InMemoryEventBus:
    def __init__(self, topic_prefix: str = "scanner") -> None:
        self.topic_prefix = topic_prefix
        self._topics: dict[str, deque[EventEnvelope]] = defaultdict(deque)

    def _qualified_topic(self, topic: str) -> str:
        return f"{self.topic_prefix}.{topic}"

    def publish(self, topic: str, payload: dict, key: str | None = None) -> EventEnvelope:
        qualified_topic = self._qualified_topic(topic)
        envelope = EventEnvelope(topic=qualified_topic, payload=payload, key=key)
        self._topics[qualified_topic].append(envelope)
        return envelope

    def consume(self, topic: str, limit: int = 100) -> list[EventEnvelope]:
        qualified_topic = self._qualified_topic(topic)
        messages: list[EventEnvelope] = []
        queue = self._topics[qualified_topic]
        while queue and len(messages) < limit:
            messages.append(queue.popleft())
        return messages


class Topics:
    RAW_LISTING_EVENTS = "raw_listing_events"
    NORMALIZED_LISTING_EVENTS = "normalized_listing_events"
    LISTING_FEATURES_READY = "listing_features_ready"
    VALUATION_REQUESTS = "valuation_requests"
    UNDERWRITING_RESULTS = "underwriting_results"
    ALERTS = "alerts"
    ACTIONS = "actions"
    OUTCOMES = "outcomes"
