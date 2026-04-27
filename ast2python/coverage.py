from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ast2python.ast.schema import ASTProgram
from ast2python.unsupported import node_kind_counts, unsupported_node_catalog


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


def static_coverage_report(program: ASTProgram) -> dict[str, Any]:
    """Schema-level coverage information that does not require successful lowering."""
    unsupported = unsupported_node_catalog(program)
    total = sum(1 for _ in program.descendants())
    unsupported_count = sum(item["count"] for item in unsupported)
    return {
        "nodes_total": total,
        "node_kind_counts": node_kind_counts(program),
        "unsupported_nodes": unsupported,
        "unsupported_node_count": unsupported_count,
        "schema_supported_ratio": 1.0 if total == 0 else (total - unsupported_count) / total,
    }
