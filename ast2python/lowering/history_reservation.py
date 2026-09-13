"""Versioned history-reservation contract shared by exact target admission and lowering."""

from __future__ import annotations

from typing import Any

from ast2python.admission.canonical import canonical_json_bytes
from ast2python.errors import BundleInvariantError

OPERATION = "state.reserve_history.v1"
CAPABILITY = "compiler.history_reservation.v1"
CONTRACT = {
    "revision": 1,
    "operation": OPERATION,
    "capability": CAPABILITY,
    "supported_pine_versions": [1, 2],
    "scalar_types": ["bool", "color", "float", "int", "string"],
    "history_policies": ["each_bar"],
    "reservation": "typed-storage-without-evaluation",
    "rollback": "transactional",
}
PARAMETER_BINDINGS = [
    {"abi_parameter": "tx", "binding": "INJECTED", "source": "RUNTIME_TRANSACTION"},
    {"abi_parameter": "series_id", "binding": "OPERATION_ARGUMENT", "source_index": 0},
    {"abi_parameter": "dtype", "binding": "OPERATION_ARGUMENT", "source_index": 1},
    {"abi_parameter": "history_policy", "binding": "OPERATION_ARGUMENT", "source_index": 2},
]


def reservation_policy(source: dict[str, Any]) -> dict[str, Any] | None:
    raw_operations = source.get("compiler_operations")
    operations = (
        [row for row in raw_operations if isinstance(row, dict) and row.get("name") == OPERATION]
        if isinstance(raw_operations, list)
        else []
    )
    if "compiled_history_reservation" not in source:
        if operations:
            raise BundleInvariantError(
                "A2P_HISTORY_RESERVATION_CONTRACT", "reservation operation lacks its contract"
            )
        return None
    if canonical_json_bytes(source["compiled_history_reservation"]) != canonical_json_bytes(
        CONTRACT
    ):
        raise BundleInvariantError(
            "A2P_HISTORY_RESERVATION_CONTRACT", "unsupported history-reservation contract"
        )
    for operation in operations:
        if operation.get(
            "abi_callable"
        ) != "pinelib.abi.primitives.reserve_history_v1" or canonical_json_bytes(
            operation.get("parameter_bindings")
        ) != canonical_json_bytes(
            PARAMETER_BINDINGS
        ):
            raise BundleInvariantError(
                "A2P_HISTORY_RESERVATION_CONTRACT", "reservation primitive ABI does not match"
            )
    # Missing/duplicate rows and policy mismatches are checked by general target admission.
    return {
        "name": OPERATION,
        "effect": "state",
        "evaluation": "eager",
        "python_name": "reserve_history_v1",
    }
