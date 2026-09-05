from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from ast2python.admission.canonical import canonical_json_bytes, freeze_json, thaw_json
from ast2python.lowering.model import (
    IRNode,
    IRSourceRef,
    IRType,
    LoweringDisposition,
    LoweringDispositionStatus,
    LoweringPlan,
)
from ast2python.lowering.recipes import LoweringRecipe, select_recipe
from ast2python.lowering.target import TargetManifest
from ast2python.session import CompilationSession

_COMPILE_TIME_DECLARATIONS = frozenset(
    {
        "pine:function:indicator",
        "pine:function:study",
        "pine:function:strategy",
        "pine:function:library",
    }
)


def _plain_attributes(value: Any) -> Any:
    if isinstance(value, Mapping):
        if isinstance(value.get("kind"), str) and isinstance(value.get("span"), Mapping):
            return {"ast_child": True, "kind": value["kind"], "span": thaw_json(value["span"])}
        return {str(key): _plain_attributes(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain_attributes(item) for item in value]
    if isinstance(value, list):
        return [_plain_attributes(item) for item in value]
    return value


def _type_from_fact(fact: Any) -> IRType | None:
    resolved = fact.resolved_type
    if resolved is None:
        return None
    return IRType(resolved.base, resolved.qualifier, resolved.nullable)


def _deterministic_ir_id(
    *, bundle_hash: str, source_node_id: str, source_kind: str, recipe: LoweringRecipe
) -> str:
    identity = {
        "bundle_hash": bundle_hash,
        "source_node_id": source_node_id,
        "recipe_id": f"{source_kind}:{recipe.opcode}",
        "target_operation_id": recipe.opcode,
        "occurrence_path": ["primary"],
    }
    return "ir:sha256:" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


def build_lowering_plan(session: CompilationSession, target: TargetManifest) -> LoweringPlan:
    session.require_production()
    bundle = session.bundle
    records: list[tuple[Any, Any, Any, LoweringRecipe]] = []
    required_operations: set[str] = set()
    for node_id in bundle.ast.ordered_node_ids:
        node = bundle.ast.node(node_id)
        fact = bundle.semantic_facts.fact_by_node_id[node_id]
        call = bundle.semantic_facts.call_by_node_id.get(node_id)
        recipe = select_recipe(
            version=bundle.version_context.pine_version,
            node=node,
            fact=fact,
            call=call,
        )
        if recipe.opcode not in target.operations:
            from ast2python.errors import BundleInvariantError

            raise BundleInvariantError(
                "A2P_TARGET_OPERATION_MISSING",
                f"target does not declare operation {recipe.opcode!r}",
                details={"node_id": node_id, "target_hash": target.content_hash},
            )
        declared = target.operations[recipe.opcode]
        if declared.evaluation != recipe.evaluation or declared.effect != recipe.effect:
            from ast2python.errors import BundleInvariantError

            raise BundleInvariantError(
                "A2P_TARGET_OPERATION_MISMATCH",
                f"target operation policy differs for {recipe.opcode!r}",
            )
        if (
            call is not None
            and not call.symbol_id.startswith("user:function:")
            and call.symbol_id not in _COMPILE_TIME_DECLARATIONS
        ):
            binding_key = (call.symbol_id, call.overload_id, call.call_form)
            binding = target.call_bindings.get(binding_key)
            if (
                binding is None
                or bundle.version_context.pine_version not in binding.supported_pine_versions
            ):
                from ast2python.errors import BundleInvariantError

                raise BundleInvariantError(
                    "A2P_TARGET_CALL_BINDING",
                    "target lacks the exact symbol/overload/call-form binding",
                    details={"node_id": node_id, "binding_key": list(binding_key)},
                )
        records.append((node, fact, call, recipe))
        required_operations.add(recipe.opcode)

    ir_id_by_source = {
        node.node_id: _deterministic_ir_id(
            bundle_hash=bundle.content_hash,
            source_node_id=node.node_id,
            source_kind=node.kind,
            recipe=recipe,
        )
        for node, _, _, recipe in records
    }
    nodes: dict[str, IRNode] = {}
    ordered: list[str] = []
    dispositions: list[LoweringDisposition] = []
    for node, fact, call, recipe in records:
        attributes: dict[str, Any] = {
            "ast_kind": node.kind,
            "fields": _plain_attributes(thaw_json(node.fields)),
            "classification": fact.classification,
            "scope_id": fact.scope_id,
            "symbol_id": fact.symbol_id,
            "overload_id": fact.overload_id,
            "call_form": fact.call_form,
            "receiver_type": fact.receiver_type,
            "coercions": thaw_json(fact.coercions),
            "stateful": fact.stateful_call,
            "const_value": thaw_json(fact.raw.get("const_value")),
            "child_roles": {
                role: [ir_id_by_source[child_id] for child_id in child_ids]
                for role, child_ids in node.child_roles.items()
            },
        }
        if call is not None:
            attributes["call"] = thaw_json(call.raw)
        ir_id = ir_id_by_source[node.node_id]
        child_ids = tuple(ir_id_by_source[child] for child in node.child_node_ids)
        nodes[ir_id] = IRNode(
            ir_id=ir_id,
            source=IRSourceRef(node_id=node.node_id, span=freeze_json(thaw_json(node.span))),
            opcode=recipe.opcode,
            result_type=_type_from_fact(fact),
            child_ir_ids=child_ids,
            attributes=freeze_json(attributes),
            semantic_rule_ids=fact.semantic_rule_ids,
            effect=recipe.effect,
            evaluation=recipe.evaluation,
        )
        ordered.append(ir_id)
        dispositions.append(
            LoweringDisposition(
                source_node_id=node.node_id,
                source_kind=node.kind,
                status=LoweringDispositionStatus.EMITTED,
                ir_ids=(ir_id,),
                reason=None,
            )
        )
    return LoweringPlan.create(
        bundle_hash=bundle.content_hash,
        source_hash=str(bundle.source["source_hash"]),
        pine_version=bundle.version_context.pine_version,
        catalog_hash=bundle.version_context.catalog_hash,
        version_context_hash=bundle.version_context.context_hash,
        target_manifest_hash=target.content_hash,
        root_ir_id=ir_id_by_source[bundle.ast.root_node_id],
        ordered_ir_ids=tuple(ordered),
        nodes=nodes,
        dispositions=tuple(dispositions),
        required_operations=frozenset(required_operations),
        required_capabilities=bundle.required_capabilities,
    )
