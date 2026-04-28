from __future__ import annotations

from collections import Counter
from typing import Any

from ast2python.lowering_matrix.loader import load_lowering_matrix, load_source_map_contract
from ast2python.lowering_matrix.schema import (
    REQUIRED_ENTRY_FIELDS,
    SOURCE_MAP_REQUIRED_FIELDS,
    STATUS_FIELDS,
    VALID_PRIORITIES,
    VALID_STATUSES,
)


class LoweringMatrixError(ValueError):
    """Raised when the AST2Python lowering matrix is invalid."""


def _fail(errors: list[str]) -> None:
    if errors:
        raise LoweringMatrixError("\n".join(errors))


def validate_lowering_matrix_payload(payload: dict[str, Any]) -> None:
    errors: list[str] = []
    if payload.get("schema_version") != "pain.ast2python.lowering_matrix.v1":
        errors.append("lowering matrix schema_version must be pain.ast2python.lowering_matrix.v1")
    if payload.get("runtime_contract") != "1.4":
        errors.append("lowering matrix runtime_contract must be 1.4")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("lowering matrix entries must be a non-empty array")
        _fail(errors)
        return

    ids: list[str] = []
    for idx, entry in enumerate(entries):
        path = f"entries[{idx}]"
        if not isinstance(entry, dict):
            errors.append(f"{path} must be an object")
            continue
        missing = REQUIRED_ENTRY_FIELDS - set(entry)
        if missing:
            errors.append(f"{path} missing fields: {sorted(missing)}")
        ast_kind = entry.get("ast_kind")
        if not isinstance(ast_kind, str) or not ast_kind:
            errors.append(f"{path}.ast_kind must be a non-empty string")
        else:
            ids.append(ast_kind)
        if entry.get("priority") not in VALID_PRIORITIES:
            errors.append(f"{path}.priority invalid: {entry.get('priority')!r}")
        if entry.get("runtime_contract") != "1.4":
            errors.append(f"{path}.runtime_contract must be 1.4")
        for field in STATUS_FIELDS:
            if entry.get(field) not in VALID_STATUSES:
                errors.append(f"{path}.{field} invalid: {entry.get(field)!r}")
        if not isinstance(entry.get("diagnostics"), list):
            errors.append(f"{path}.diagnostics must be an array")
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate lowering matrix ast_kind values: {duplicates}")
    _fail(errors)


def validate_source_map_contract_payload(payload: dict[str, Any]) -> None:
    errors: list[str] = []
    if payload.get("schema_version") != "pain.ast2python.source_map_contract.v1":
        errors.append(
            "source-map contract schema_version must be pain.ast2python.source_map_contract.v1"
        )
    if payload.get("runtime_contract") != "1.4":
        errors.append("source-map contract runtime_contract must be 1.4")
    required_fields = payload.get("required_fields")
    if not isinstance(required_fields, list):
        errors.append("source-map contract required_fields must be an array")
    else:
        missing = sorted(SOURCE_MAP_REQUIRED_FIELDS - set(required_fields))
        if missing:
            errors.append(f"source-map contract missing required fields: {missing}")
    if payload.get("format") != "json-array":
        errors.append("source-map contract format must be json-array")
    _fail(errors)


def validate_lowering_matrix(path: str | None = None) -> None:
    validate_lowering_matrix_payload(load_lowering_matrix(path))


def validate_source_map_contract(path: str | None = None) -> None:
    validate_source_map_contract_payload(load_source_map_contract(path))
