from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_STATUSES = {
    "NOT_STARTED",
    "PARTIAL",
    "IMPLEMENTED_UNVERIFIED",
    "DONE_VERIFIED",
    "UNSUPPORTED_DIAGNOSTIC",
    "NOT_APPLICABLE",
    "BLOCKED_BY_TV_EXPORT",
}
VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
REQUIRED_ENTRY_FIELDS = {
    "ast_kind",
    "category",
    "priority",
    "runtime_contract",
    "lowering_status",
    "source_map_status",
    "coverage_status",
    "owner_method",
    "diagnostics",
    "notes",
}
STATUS_FIELDS = ("lowering_status", "source_map_status", "coverage_status")
SOURCE_MAP_REQUIRED_FIELDS = {
    "python_line",
    "pine_line",
    "pine_column",
    "pine_end_line",
    "pine_end_column",
    "pine_source",
}


@dataclass(frozen=True, slots=True)
class LoweringMatrixEntry:
    ast_kind: str
    category: str
    priority: str
    runtime_contract: str
    lowering_status: str
    source_map_status: str
    coverage_status: str
    owner_method: str
    diagnostics: list[str]
    notes: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoweringMatrixEntry:
        return cls(
            ast_kind=str(data["ast_kind"]),
            category=str(data["category"]),
            priority=str(data["priority"]),
            runtime_contract=str(data["runtime_contract"]),
            lowering_status=str(data["lowering_status"]),
            source_map_status=str(data["source_map_status"]),
            coverage_status=str(data["coverage_status"]),
            owner_method=str(data["owner_method"]),
            diagnostics=[str(item) for item in data["diagnostics"]],
            notes=str(data["notes"]),
        )
