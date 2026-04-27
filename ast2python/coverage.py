from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CoverageTracker:
    nodes_total: int = 0
    nodes_generated: int = 0
    nodes_unsupported: int = 0
    builtins: Counter[str] = field(default_factory=Counter)

    def seen(self) -> None:
        self.nodes_total += 1

    def generated(self) -> None:
        self.nodes_generated += 1

    def unsupported(self) -> None:
        self.nodes_unsupported += 1

    def builtin(self, name: str) -> None:
        self.builtins[name] += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes_total": self.nodes_total,
            "nodes_generated": self.nodes_generated,
            "nodes_unsupported": self.nodes_unsupported,
            "generation_ratio": 0.0 if self.nodes_total == 0 else self.nodes_generated / self.nodes_total,
            "builtins": dict(sorted(self.builtins.items())),
        }
