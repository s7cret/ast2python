from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ast2python.compiler import compile_reference_consumer_bundle as compile_consumer_bundle
from ast2python.emission import verify_source_map_v2
from ast2python.lowering import load_reference_target_manifest, validate_lowering_plan
from ast2python.lowering.recipes import supported_ast_kinds


def run_property_gate(bundle_paths: Sequence[str | Path]) -> dict[str, Any]:
    target_a = load_reference_target_manifest()
    target_b = load_reference_target_manifest()
    findings: list[dict[str, Any]] = []
    checked = 0
    if not bundle_paths:
        findings.append({"code": "A2P_PROPERTY_INPUTS"})
    if target_a.to_dict() != target_b.to_dict():
        findings.append({"code": "TARGET_MATERIALIZATION_UNSTABLE"})
    for source in bundle_paths:
        path = Path(source)
        first = compile_consumer_bundle(path, module_name="property_module")
        second = compile_consumer_bundle(path, module_name="property_module")
        checked += 1
        if first.plan.to_dict() != second.plan.to_dict():
            findings.append({"code": "PLAN_IDENTITY_UNSTABLE", "path": str(path)})
        if first.emitted.code != second.emitted.code:
            findings.append({"code": "EMISSION_UNSTABLE", "path": str(path)})
        if first.artifact.to_dict() != second.artifact.to_dict():
            findings.append({"code": "ARTIFACT_UNSTABLE", "path": str(path)})
        validate_lowering_plan(first.plan, target_a)
        verify_source_map_v2(
            first.emitted.source_map.to_dict(), expected_ir_ids=set(first.plan.nodes)
        )
        source_ids = [first.plan.nodes[ir_id].source.node_id for ir_id in first.plan.ordered_ir_ids]
        if len(source_ids) != len(set(source_ids)):
            findings.append({"code": "DUPLICATE_SOURCE_ID", "path": str(path)})
        if tuple(first.plan.nodes) != first.plan.ordered_ir_ids:
            findings.append({"code": "PLAN_ORDER_MISMATCH", "path": str(path)})
        if set(first.plan.required_operations) - set(target_a.operations):
            findings.append({"code": "TARGET_OPERATION_SUBSET", "path": str(path)})
        starts = [
            (entry.python_start.line, entry.python_start.column)
            for entry in first.emitted.source_map.entries
        ]
        if starts != sorted(starts):
            findings.append({"code": "SOURCE_MAP_RANGE_ORDER", "path": str(path)})
        ast_kinds = {str(node.attributes.get("ast_kind")) for node in first.plan.nodes.values()}
        unknown = ast_kinds - supported_ast_kinds()
        if unknown:
            findings.append(
                {
                    "code": "UNUSED_RECIPE_OR_UNKNOWN_KIND",
                    "path": str(path),
                    "kinds": sorted(unknown),
                }
            )
    return {
        "schema_id": "ast2python.stage4.properties.v1",
        "ok": not findings,
        "checked_bundles": checked,
        "findings": findings,
    }
