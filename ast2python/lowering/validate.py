from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from ast2python.admission.canonical import canonical_json_bytes
from ast2python.errors import BundleInvariantError
from ast2python.lowering.model import LoweringDispositionStatus, LoweringPlan
from ast2python.lowering.target import TargetManifest

_PLAN_FIELDS = {
    "schema_id",
    "schema_version",
    "bundle_hash",
    "source_hash",
    "pine_version",
    "catalog_hash",
    "version_context_hash",
    "target_manifest_hash",
    "root_ir_id",
    "ordered_ir_ids",
    "nodes",
    "dispositions",
    "required_operations",
    "required_capabilities",
    "content_hash",
}
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_NODE_FIELDS = {
    "ir_id",
    "source",
    "opcode",
    "result_type",
    "child_ir_ids",
    "attributes",
    "semantic_rule_ids",
    "effect",
    "evaluation",
}
_DISPOSITION_FIELDS = {"source_node_id", "source_kind", "status", "ir_ids", "reason"}
_REQUIRES_IR = {
    LoweringDispositionStatus.EMITTED.value,
    LoweringDispositionStatus.EXPANDED.value,
    LoweringDispositionStatus.DELEGATED.value,
}


def validate_lowering_plan(plan: LoweringPlan, target: TargetManifest) -> None:
    verify_lowering_plan_payload(plan.to_dict(), target=target)


def verify_lowering_plan_payload(value: Mapping[str, Any], *, target: TargetManifest) -> None:
    if set(value) != _PLAN_FIELDS:
        raise BundleInvariantError("A2P_PLAN_FIELDS", "lowering plan fields are not exact")
    if (
        value.get("schema_id") != "ast2python.lowering_plan.v2"
        or value.get("schema_version") != "2.0.0"
    ):
        raise BundleInvariantError("A2P_PLAN_SCHEMA", "unsupported lowering plan schema")
    body = {key: value[key] for key in value if key != "content_hash"}
    expected = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    if value.get("content_hash") != expected:
        raise BundleInvariantError("A2P_PLAN_HASH", "lowering plan content hash mismatch")
    for field in (
        "bundle_hash",
        "source_hash",
        "catalog_hash",
        "version_context_hash",
        "target_manifest_hash",
        "content_hash",
    ):
        if (
            not isinstance(value.get(field), str)
            or _HASH_RE.fullmatch(str(value.get(field))) is None
        ):
            raise BundleInvariantError("A2P_PLAN_HASH_FORMAT", f"{field} must be a sha256 identity")
    if value.get("target_manifest_hash") != target.content_hash:
        raise BundleInvariantError("A2P_PLAN_TARGET_HASH", "plan target hash mismatch")
    pine_version = value.get("pine_version")
    if type(pine_version) is not int or pine_version not in range(1, 7):
        raise BundleInvariantError("A2P_PLAN_VERSION", "plan Pine version must be 1..6")

    ordered = value.get("ordered_ir_ids")
    nodes = value.get("nodes")
    if not isinstance(ordered, list) or not all(isinstance(item, str) and item for item in ordered):
        raise BundleInvariantError("A2P_PLAN_ORDER", "ordered_ir_ids must be non-empty strings")
    if not isinstance(nodes, list) or not all(isinstance(item, Mapping) for item in nodes):
        raise BundleInvariantError("A2P_PLAN_NODES", "nodes must be objects")
    if len(ordered) != len(nodes) or len(ordered) != len(set(ordered)):
        raise BundleInvariantError("A2P_PLAN_NODE_SET", "IR IDs must be unique and complete")

    by_id: dict[str, Mapping[str, Any]] = {}
    used_operations: set[str] = set()
    for index, node in enumerate(nodes):
        if set(node) != _NODE_FIELDS:
            raise BundleInvariantError(
                "A2P_PLAN_NODE_FIELDS",
                "IR node fields are not exact",
                path=f"$.nodes[{index}]",
            )
        ir_id = node.get("ir_id")
        if not isinstance(ir_id, str) or not ir_id or ir_id in by_id:
            raise BundleInvariantError(
                "A2P_PLAN_NODE_ID",
                "IR node identity must be unique",
                path=f"$.nodes[{index}].ir_id",
            )
        by_id[ir_id] = node
        source = node.get("source")
        if not isinstance(source, Mapping) or set(source) != {"node_id", "span"}:
            raise BundleInvariantError("A2P_PLAN_SOURCE", "source reference fields are not exact")
        source_id = source.get("node_id")
        if not isinstance(source_id, str) or not source_id:
            raise BundleInvariantError("A2P_PLAN_SOURCE", "source node identity must be non-empty")
        opcode = node.get("opcode")
        if not isinstance(opcode, str) or opcode not in target.operations:
            raise BundleInvariantError("A2P_PLAN_OPERATION", f"unknown target operation {opcode!r}")
        used_operations.add(opcode)
        declared = target.operations[opcode]
        if node.get("evaluation") != declared.evaluation or node.get("effect") != declared.effect:
            raise BundleInvariantError("A2P_PLAN_POLICY", "IR operation policy differs from target")
        children = node.get("child_ir_ids")
        if not isinstance(children, list) or not all(
            isinstance(child, str) and child for child in children
        ):
            raise BundleInvariantError("A2P_PLAN_CHILDREN", "child_ir_ids must be strings")
        rules = node.get("semantic_rule_ids")
        if not isinstance(rules, list) or not all(isinstance(item, str) and item for item in rules):
            raise BundleInvariantError("A2P_PLAN_RULES", "semantic_rule_ids must be strings")
        result_type = node.get("result_type")
        if result_type is not None:
            if not isinstance(result_type, Mapping) or set(result_type) != {
                "base",
                "qualifier",
                "nullable",
            }:
                raise BundleInvariantError(
                    "A2P_PLAN_RESULT_TYPE", "result_type fields are not exact"
                )
            if not isinstance(result_type.get("base"), str) or not result_type.get("base"):
                raise BundleInvariantError("A2P_PLAN_RESULT_TYPE", "result_type base is required")
            if result_type.get("qualifier") not in {"const", "input", "simple", "series"}:
                raise BundleInvariantError(
                    "A2P_PLAN_RESULT_TYPE", "result_type qualifier is invalid"
                )
            if type(result_type.get("nullable")) is not bool:
                raise BundleInvariantError(
                    "A2P_PLAN_RESULT_TYPE", "result_type nullable must be boolean"
                )
        if not isinstance(node.get("attributes"), Mapping):
            raise BundleInvariantError("A2P_PLAN_ATTRIBUTES", "attributes must be an object")
    if ordered != [node.get("ir_id") for node in nodes]:
        raise BundleInvariantError(
            "A2P_PLAN_ORDER", "ordered_ir_ids must match node serialization order"
        )
    if value.get("root_ir_id") not in by_id:
        raise BundleInvariantError("A2P_PLAN_ROOT", "plan root is missing")
    for ir_id, node in by_id.items():
        for child in node["child_ir_ids"]:
            if child not in by_id:
                raise BundleInvariantError(
                    "A2P_PLAN_CHILD", f"IR child {child!r} is missing", path=ir_id
                )

    dispositions = value.get("dispositions")
    if not isinstance(dispositions, list) or not all(
        isinstance(item, Mapping) for item in dispositions
    ):
        raise BundleInvariantError("A2P_PLAN_DISPOSITIONS", "dispositions must be objects")
    source_ids: set[str] = set()
    owned_ir_ids: set[str] = set()
    valid_statuses = {status.value for status in LoweringDispositionStatus}
    for index, disposition in enumerate(dispositions):
        if set(disposition) != _DISPOSITION_FIELDS:
            raise BundleInvariantError(
                "A2P_PLAN_DISPOSITION_FIELDS",
                "disposition fields are not exact",
                path=f"$.dispositions[{index}]",
            )
        source_id = disposition.get("source_node_id")
        source_kind = disposition.get("source_kind")
        if not isinstance(source_id, str) or not source_id or source_id in source_ids:
            raise BundleInvariantError(
                "A2P_PLAN_DISPOSITION_SOURCE",
                "every source node must have one unique disposition",
            )
        source_ids.add(source_id)
        if not isinstance(source_kind, str) or not source_kind:
            raise BundleInvariantError(
                "A2P_PLAN_DISPOSITION_KIND", "disposition source_kind is required"
            )
        status = disposition.get("status")
        if status not in valid_statuses:
            raise BundleInvariantError(
                "A2P_PLAN_DISPOSITION_STATUS", "unknown lowering disposition status"
            )
        ir_ids = disposition.get("ir_ids")
        if not isinstance(ir_ids, list) or not all(
            isinstance(ir_id, str) and ir_id for ir_id in ir_ids
        ):
            raise BundleInvariantError(
                "A2P_PLAN_IR_OWNERSHIP", "disposition ir_ids must be strings"
            )
        if status in _REQUIRES_IR and not ir_ids:
            raise BundleInvariantError(
                "A2P_PLAN_DISPOSITION_STATUS", f"{status} disposition requires IR"
            )
        if status == LoweringDispositionStatus.REJECTED.value:
            raise BundleInvariantError(
                "A2P_PLAN_REJECTED", "rejected source blocks a valid lowering plan"
            )
        reason = disposition.get("reason")
        if reason is not None and (not isinstance(reason, str) or not reason):
            raise BundleInvariantError(
                "A2P_PLAN_DISPOSITION_REASON", "reason must be null or a non-empty string"
            )
        for ir_id in ir_ids:
            if ir_id in owned_ir_ids or ir_id not in by_id:
                raise BundleInvariantError(
                    "A2P_PLAN_IR_OWNERSHIP", "every IR ID must be owned exactly once"
                )
            owned_ir_ids.add(ir_id)
            node = by_id[ir_id]
            source = node["source"]
            attributes = node["attributes"]
            if source.get("node_id") != source_id or attributes.get("ast_kind") != source_kind:
                raise BundleInvariantError(
                    "A2P_PLAN_IR_OWNERSHIP", "IR source differs from its disposition owner"
                )
    if owned_ir_ids != set(by_id):
        raise BundleInvariantError(
            "A2P_PLAN_IR_OWNERSHIP",
            "every IR ID must be owned exactly once",
            details={
                "missing": sorted(set(by_id) - owned_ir_ids),
                "extra": sorted(owned_ir_ids - set(by_id)),
            },
        )

    required_operations = value.get("required_operations")
    if not isinstance(required_operations, list) or required_operations != sorted(
        set(required_operations)
    ):
        raise BundleInvariantError(
            "A2P_PLAN_REQUIRED_OPERATION", "required_operations must be sorted and unique"
        )
    if set(required_operations) != used_operations:
        raise BundleInvariantError(
            "A2P_PLAN_REQUIRED_OPERATION", "required_operations differ from used operations"
        )
    unknown_required = set(required_operations) - set(target.operations)
    if unknown_required:
        raise BundleInvariantError(
            "A2P_PLAN_REQUIRED_OPERATION",
            "plan requires unknown operations",
            details={"unknown": sorted(unknown_required)},
        )
    capabilities = value.get("required_capabilities")
    if not isinstance(capabilities, list) or capabilities != sorted(set(capabilities)):
        raise BundleInvariantError(
            "A2P_PLAN_CAPABILITY", "required_capabilities must be sorted and unique"
        )
    missing_capabilities = set(capabilities) - set(target.capabilities)
    if missing_capabilities:
        raise BundleInvariantError(
            "A2P_PLAN_CAPABILITY",
            "target lacks required consumer capabilities",
            details={"missing": sorted(missing_capabilities)},
        )
