from __future__ import annotations

from dataclasses import dataclass, fields

from ast2python.errors import BundleLimitError


@dataclass(frozen=True, slots=True)
class AbsoluteAdmissionLimits:
    max_bundle_bytes: int = 64 * 1024 * 1024
    max_json_depth: int = 256
    max_total_json_nodes: int = 8_000_000
    max_container_items: int = 1_000_000
    max_ast_nodes: int = 2_000_000
    max_facts: int = 2_000_000
    max_calls: int = 500_000
    max_diagnostics: int = 20_000
    max_linked_artifacts: int = 128
    max_string_length: int = 2 * 1024 * 1024
    max_dependency_count: int = 4_096


ABSOLUTE_LIMITS = AbsoluteAdmissionLimits()


@dataclass(frozen=True, slots=True)
class AdmissionLimits:
    max_bundle_bytes: int = 16 * 1024 * 1024
    max_json_depth: int = 128
    max_total_json_nodes: int = 1_000_000
    max_container_items: int = 100_000
    max_ast_nodes: int = 500_000
    max_facts: int = 500_000
    max_calls: int = 100_000
    max_diagnostics: int = 5_000
    max_linked_artifacts: int = 32
    max_string_length: int = 1 * 1024 * 1024
    max_dependency_count: int = 1_024

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            ceiling = getattr(ABSOLUTE_LIMITS, item.name)
            if type(value) is not int or value < 1:
                raise BundleLimitError(
                    "A2P_LIMIT_INVALID",
                    f"{item.name} must be a positive integer",
                    path=f"$.limits.{item.name}",
                )
            if value > ceiling:
                raise BundleLimitError(
                    "A2P_LIMIT_ABOVE_ABSOLUTE",
                    f"{item.name} exceeds the absolute ceiling {ceiling}",
                    path=f"$.limits.{item.name}",
                )
