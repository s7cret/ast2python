from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ast2python.admission.canonical import canonical_json_bytes
from ast2python.errors import BundleInvariantError


@dataclass(frozen=True, slots=True)
class PythonPosition:
    line: int
    column: int

    def to_dict(self) -> dict[str, int]:
        return {"line": self.line, "column": self.column}


@dataclass(frozen=True, slots=True)
class SourceMapEntry:
    python_start: PythonPosition
    python_end: PythonPosition
    source_node_id: str | None
    source_span: dict[str, Any] | None
    ir_id: str | None
    origin: Literal["PINE", "LOWERING", "SCAFFOLD"]
    semantic_rule_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "python_start": self.python_start.to_dict(),
            "python_end": self.python_end.to_dict(),
            "source_node_id": self.source_node_id,
            "source_span": None if self.source_span is None else dict(self.source_span),
            "ir_id": self.ir_id,
            "origin": self.origin,
            "semantic_rule_ids": list(self.semantic_rule_ids),
        }


@dataclass(frozen=True, slots=True)
class SourceMapV2:
    entries: tuple[SourceMapEntry, ...]
    content_hash: str

    def to_body_dict(self) -> dict[str, Any]:
        return {
            "schema_id": "openpine.source_map.v2",
            "schema_version": "2.0.0",
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def to_dict(self) -> dict[str, Any]:
        body = self.to_body_dict()
        body["content_hash"] = self.content_hash
        return body

    @classmethod
    def create(cls, entries: tuple[SourceMapEntry, ...]) -> SourceMapV2:
        body = {
            "schema_id": "openpine.source_map.v2",
            "schema_version": "2.0.0",
            "entries": [entry.to_dict() for entry in entries],
        }
        digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        return cls(entries=entries, content_hash=f"sha256:{digest}")


def _position(value: Any, *, path: str) -> tuple[int, int]:
    if not isinstance(value, Mapping) or set(value) != {"line", "column"}:
        raise BundleInvariantError(
            "A2P_SOURCE_MAP_POSITION", "position fields are not exact", path=path
        )
    line = value.get("line")
    column = value.get("column")
    if type(line) is not int or line <= 0 or type(column) is not int or column < 0:
        raise BundleInvariantError("A2P_SOURCE_MAP_POSITION", "position is invalid", path=path)
    return line, column


def verify_source_map_v2(
    value: Mapping[str, Any], *, expected_ir_ids: set[str] | None = None
) -> None:
    if set(value) != {"schema_id", "schema_version", "entries", "content_hash"}:
        raise BundleInvariantError("A2P_SOURCE_MAP_FIELDS", "source map fields are not exact")
    if value.get("schema_id") != "openpine.source_map.v2" or value.get("schema_version") != "2.0.0":
        raise BundleInvariantError("A2P_SOURCE_MAP_SCHEMA", "unsupported source map schema")
    body = {key: value[key] for key in value if key != "content_hash"}
    expected = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    if value.get("content_hash") != expected:
        raise BundleInvariantError("A2P_SOURCE_MAP_HASH", "source map content hash mismatch")
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise BundleInvariantError("A2P_SOURCE_MAP_ENTRIES", "source map entries must be an array")
    ir_ids: set[str] = set()
    required_fields = {
        "python_start",
        "python_end",
        "source_node_id",
        "source_span",
        "ir_id",
        "origin",
        "semantic_rule_ids",
    }
    for index, entry in enumerate(entries):
        path = f"$.entries[{index}]"
        if not isinstance(entry, Mapping) or set(entry) != required_fields:
            raise BundleInvariantError(
                "A2P_SOURCE_MAP_ENTRY", "source map entry fields are not exact", path=path
            )
        start = _position(entry.get("python_start"), path=f"{path}.python_start")
        end = _position(entry.get("python_end"), path=f"{path}.python_end")
        if end < start:
            raise BundleInvariantError(
                "A2P_SOURCE_MAP_RANGE", "Python range is reversed", path=path
            )
        origin = entry.get("origin")
        if origin not in {"PINE", "LOWERING", "SCAFFOLD"}:
            raise BundleInvariantError(
                "A2P_SOURCE_MAP_ORIGIN", "source map origin is invalid", path=path
            )
        ir_id = entry.get("ir_id")
        source_node_id = entry.get("source_node_id")
        source_span = entry.get("source_span")
        rules = entry.get("semantic_rule_ids")
        if not isinstance(rules, list) or not all(isinstance(rule, str) and rule for rule in rules):
            raise BundleInvariantError(
                "A2P_SOURCE_MAP_RULES", "semantic rules must be strings", path=path
            )
        if origin == "SCAFFOLD":
            if source_node_id is not None or source_span is not None:
                raise BundleInvariantError(
                    "A2P_SOURCE_MAP_SCAFFOLD", "scaffold must not fabricate Pine source", path=path
                )
        else:
            if not isinstance(source_node_id, str) or not source_node_id:
                raise BundleInvariantError(
                    "A2P_SOURCE_MAP_SOURCE", "source node ID is required", path=path
                )
            if not isinstance(source_span, Mapping):
                raise BundleInvariantError(
                    "A2P_SOURCE_MAP_SPAN", "source span must be an object", path=path
                )
        if ir_id is not None:
            if not isinstance(ir_id, str) or not ir_id or ir_id in ir_ids:
                raise BundleInvariantError(
                    "A2P_SOURCE_MAP_IR", "IR IDs must be unique when present", path=path
                )
            ir_ids.add(ir_id)
    if expected_ir_ids is not None and ir_ids != expected_ir_ids:
        raise BundleInvariantError(
            "A2P_SOURCE_MAP_COVERAGE",
            "source map must cover every IR node exactly once",
            details={
                "missing": sorted(expected_ir_ids - ir_ids),
                "extra": sorted(ir_ids - expected_ir_ids),
            },
        )
