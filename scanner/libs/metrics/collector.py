from __future__ import annotations

from collections import Counter, defaultdict


class MetricsCollector:
    def __init__(self) -> None:
        self.counters: Counter[str] = Counter()
        self.histograms: dict[str, list[float]] = defaultdict(list)

    def increment(self, name: str, value: int = 1) -> None:
        self.counters[name] += value

    def observe(self, name: str, value: float) -> None:
        self.histograms[name].append(value)

    def snapshot(self) -> dict[str, dict[str, float | int | list[float]]]:
        return {
            "counters": dict(self.counters),
            "histograms": dict(self.histograms),
        }
