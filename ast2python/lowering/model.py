from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ast2python.admission.canonical import canonical_json_bytes, thaw_json


@dataclass(frozen=True, slots=True)
class IRType:
    base: str
    qualifier: str
    nullable: bool

    def to_dict(self) -> dict[str, Any]:
        return {"base": self.base, "qualifier": self.qualifier, "nullable": self.nullable}


@dataclass(frozen=True, slots=True)
class IRSourceRef:
    node_id: str
    span: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "span": thaw_json(self.span)}


@dataclass(frozen=True, slots=True)
class IRNode:
    ir_id: str
    source: IRSourceRef
    opcode: str
    result_type: IRType | None
    child_ir_ids: tuple[str, ...]
    attributes: Mapping[str, Any]
    semantic_rule_ids: tuple[str, ...]
    effect: str
    evaluation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ir_id": self.ir_id,
            "source": self.source.to_dict(),
            "opcode": self.opcode,
            "result_type": None if self.result_type is None else self.result_type.to_dict(),
            "child_ir_ids": list(self.child_ir_ids),
            "attributes": thaw_json(self.attributes),
            "semantic_rule_ids": list(self.semantic_rule_ids),
            "effect": self.effect,
            "evaluation": self.evaluation,
        }


class LoweringDispositionStatus(StrEnum):
    EMITTED = "EMITTED"
    COMPILE_TIME_ONLY = "COMPILE_TIME_ONLY"
    FOLDED = "FOLDED"
    EXPANDED = "EXPANDED"
    DELEGATED = "DELEGATED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class LoweringDisposition:
    source_node_id: str
    source_kind: str
    status: LoweringDispositionStatus
    ir_ids: tuple[str, ...]
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_node_id": self.source_node_id,
            "source_kind": self.source_kind,
            "status": self.status.value,
            "ir_ids": list(self.ir_ids),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LoweringPlan:
    schema_id: str
    schema_version: str
    bundle_hash: str
    source_hash: str
    pine_version: int
    catalog_hash: str
    version_context_hash: str
    target_manifest_hash: str
    root_ir_id: str
    ordered_ir_ids: tuple[str, ...]
    nodes: Mapping[str, IRNode]
    dispositions: tuple[LoweringDisposition, ...]
    required_operations: frozenset[str]
    required_capabilities: frozenset[str]
    content_hash: str

    def to_body_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "bundle_hash": self.bundle_hash,
            "source_hash": self.source_hash,
            "pine_version": self.pine_version,
            "catalog_hash": self.catalog_hash,
            "version_context_hash": self.version_context_hash,
            "target_manifest_hash": self.target_manifest_hash,
            "root_ir_id": self.root_ir_id,
            "ordered_ir_ids": list(self.ordered_ir_ids),
            "nodes": [self.nodes[node_id].to_dict() for node_id in self.ordered_ir_ids],
            "dispositions": [disposition.to_dict() for disposition in self.dispositions],
            "required_operations": sorted(self.required_operations),
            "required_capabilities": sorted(self.required_capabilities),
        }

    def to_dict(self) -> dict[str, Any]:
        body = self.to_body_dict()
        body["content_hash"] = self.content_hash
        return body

    @classmethod
    def create(
        cls,
        *,
        bundle_hash: str,
        source_hash: str,
        pine_version: int,
        catalog_hash: str,
        version_context_hash: str,
        target_manifest_hash: str,
        root_ir_id: str,
        ordered_ir_ids: tuple[str, ...],
        nodes: Mapping[str, IRNode],
        dispositions: tuple[LoweringDisposition, ...],
        required_operations: frozenset[str],
        required_capabilities: frozenset[str],
    ) -> LoweringPlan:
        import hashlib

        proxy = MappingProxyType(dict(nodes))
        provisional = cls(
            schema_id="ast2python.lowering_plan.v2",
            schema_version="2.0.0",
            bundle_hash=bundle_hash,
            source_hash=source_hash,
            pine_version=pine_version,
            catalog_hash=catalog_hash,
            version_context_hash=version_context_hash,
            target_manifest_hash=target_manifest_hash,
            root_ir_id=root_ir_id,
            ordered_ir_ids=ordered_ir_ids,
            nodes=proxy,
            dispositions=dispositions,
            required_operations=required_operations,
            required_capabilities=required_capabilities,
            content_hash="",
        )
        digest = hashlib.sha256(canonical_json_bytes(provisional.to_body_dict())).hexdigest()
        return replace(provisional, content_hash=f"sha256:{digest}")
