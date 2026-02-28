from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class MetricsRegistry:
    counters: Counter[str] = field(default_factory=Counter)

    def inc(self, key: str, value: int = 1) -> None:
        if value <= 0:
            return
        self.counters[key] += value

    def snapshot(self) -> dict[str, int]:
        return dict(self.counters)


metrics = MetricsRegistry()
