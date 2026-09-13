"""Represent history reservation as owned IR, not an unrecorded emitter side effect."""

from __future__ import annotations

import hashlib
from dataclasses import replace

from ast2python.admission.canonical import canonical_json_bytes, freeze_json, thaw_json
from ast2python.errors import BundleInvariantError
from ast2python.lowering.history_reservation import CAPABILITY, OPERATION
from ast2python.lowering.model import IRNode, LoweringDispositionStatus, LoweringPlan
from ast2python.lowering.target import TargetManifest


def expand_history_reservations(plan: LoweringPlan, target: TargetManifest) -> LoweringPlan:
    if (
        target.release_acceptance != "EXACT_PINELIB_TARGET_MANIFEST_V2"
        or plan.pine_version not in {1, 2}
    ):
        return plan
    attrs = {key: thaw_json(node.attributes) for key, node in plan.nodes.items()}
    root = attrs[plan.root_ir_id]
    items = root.get("child_roles", {}).get("items", [])
    declarations = {
        attrs[key]["symbol_id"]: key
        for key in items
        if attrs[key].get("ast_kind") == "VarDeclaration"
        and isinstance(attrs[key].get("symbol_id"), str)
    }
    selected: dict[str, str] = {}
    for key in plan.ordered_ir_ids:
        if attrs[key].get("ast_kind") != "HistoryRefExpr":
            continue
        bases = attrs[key].get("child_roles", {}).get("base", [])
        if len(bases) != 1:
            continue  # Existing expression validation rejects malformed history shapes.
        base = attrs[bases[0]]
        symbol = base.get("symbol_id")
        declaration = declarations.get(symbol)
        if declaration is not None:
            selected.setdefault(declaration, key)
        elif isinstance(symbol, str) and symbol.startswith("user:variable:"):
            raise BundleInvariantError(
                "A2P_LEXICAL_BINDING_IDENTITY",
                "history needs an exact producer declaration identity",
            )
    if not selected:
        return plan
    if CAPABILITY not in target.capabilities or OPERATION not in target.operations:
        raise BundleInvariantError(
            "A2P_HISTORY_RESERVATION_CONTRACT", "target lacks the declared history-reservation ABI"
        )
    nodes = dict(plan.nodes)
    ordered = list(plan.ordered_ir_ids)
    dispositions = list(plan.dispositions)
    ownership = {row.source_node_id: index for index, row in enumerate(dispositions)}
    reservations = []
    for declaration, history in selected.items():
        owner = nodes[history]
        identity = {
            "history_ir_id": history,
            "declaration_ir_id": declaration,
            "operation": OPERATION,
        }
        key = "ir:sha256:" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        nodes[key] = IRNode(
            ir_id=key,
            source=owner.source,
            opcode=OPERATION,
            result_type=None,
            child_ir_ids=(),
            attributes=freeze_json(
                {
                    "ast_kind": "HistoryRefExpr",
                    "lowering_role": "history_reservation",
                    "scope_id": "scope:global",
                    "fields": {"declaration_ir_id": declaration},
                    "child_roles": {},
                }
            ),
            semantic_rule_ids=owner.semantic_rule_ids,
            effect="state",
            evaluation="eager",
        )
        ordered.append(key)
        reservations.append(key)
        index = ownership[owner.source.node_id]
        row = dispositions[index]
        dispositions[index] = replace(
            row, status=LoweringDispositionStatus.EXPANDED, ir_ids=(*row.ir_ids, key)
        )
    root["child_roles"]["history_reservations"] = reservations
    nodes[plan.root_ir_id] = replace(
        nodes[plan.root_ir_id],
        attributes=freeze_json(root),
        child_ir_ids=(*nodes[plan.root_ir_id].child_ir_ids, *reservations),
    )
    return LoweringPlan.create(
        bundle_hash=plan.bundle_hash,
        source_hash=plan.source_hash,
        pine_version=plan.pine_version,
        catalog_hash=plan.catalog_hash,
        version_context_hash=plan.version_context_hash,
        target_manifest_hash=plan.target_manifest_hash,
        root_ir_id=plan.root_ir_id,
        ordered_ir_ids=tuple(ordered),
        nodes=nodes,
        dispositions=tuple(dispositions),
        required_operations=plan.required_operations | {OPERATION},
        required_capabilities=plan.required_capabilities | {CAPABILITY},
    )
