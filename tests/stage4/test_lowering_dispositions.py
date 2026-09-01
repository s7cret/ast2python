from __future__ import annotations

import copy
import hashlib
import inspect
import re
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from pine2ast.ast import nodes as producer_nodes
from pine2ast.ast.base import ASTNode
from pine2ast.ast.types import TypeRef
from pine2ast.lexer.token import SourceSpan

from ast2python import (
    BundleInvariantError,
    admit_consumer_bundle,
)
from ast2python import (
    compile_reference_consumer_bundle as compile_consumer_bundle,
)
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.admission.facts import SemanticFactView
from ast2python.artifacts import build_generated_artifact_v3, verify_generated_artifact_v3
from ast2python.emission import emit_python_module, verify_source_map_v2
from ast2python.lowering import (
    LoweringDisposition,
    LoweringDispositionStatus,
    LoweringPlan,
    load_reference_target_manifest,
    supported_ast_kinds,
    validate_lowering_plan,
)
from ast2python.lowering.recipes import select_recipe
from ast2python.lowering.validate import verify_lowering_plan_payload

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "consumer"
BUNDLE_V2 = FIXTURES / "pine-v2-consumer-bundle.json"
BUNDLE_V6 = FIXTURES / "pine-v6-consumer-bundle.json"


def _nodes_of_kind(view: Any, kind: str) -> list[Any]:
    return [
        view.node(node_id) for node_id in view.ordered_node_ids if view.node(node_id).kind == kind
    ]


def test_child_roles_preserve_top_level_call_if_and_program_roles() -> None:
    view = admit_consumer_bundle(BUNDLE_V2).ast
    program = view.node(view.root_node_id)
    call = _nodes_of_kind(view, "CallExpr")[0]
    if_node = _nodes_of_kind(view, "IfStructure")[0]

    assert set(program.child_roles) == {"declaration", "items"}
    assert [view.node(node_id).kind for node_id in program.child_roles["declaration"]] == [
        "DeclarationStatement"
    ]
    assert program.child_roles["items"]

    assert set(call.child_roles) == {"arguments", "callee"}
    assert [view.node(node_id).kind for node_id in call.child_roles["callee"]] == ["Identifier"]
    assert [view.node(node_id).kind for node_id in call.child_roles["arguments"]] == ["Argument"]

    assert set(if_node.child_roles) == {"condition", "else_block", "then_block"}
    assert [view.node(node_id).kind for node_id in if_node.child_roles["condition"]] == [
        "BinaryExpr"
    ]
    assert [view.node(node_id).kind for node_id in if_node.child_roles["then_block"]] == ["Block"]
    assert [view.node(node_id).kind for node_id in if_node.child_roles["else_block"]] == ["Block"]
    assert program.child_node_ids == tuple(
        child_id for ids in program.child_roles.values() for child_id in ids
    )
    assert view.child_roles_by_node_id[program.node_id] is program.child_roles


def test_child_roles_are_immutable_and_serialize_as_ordered_lists() -> None:
    view = admit_consumer_bundle(BUNDLE_V2).ast
    call = _nodes_of_kind(view, "CallExpr")[0]

    with pytest.raises(TypeError):
        call.child_roles["callee"] = ()
    with pytest.raises(TypeError):
        view.child_roles_by_node_id[call.node_id] = MappingProxyType({})
    assert call.to_dict()["child_roles"] == {
        role: list(node_ids) for role, node_ids in call.child_roles.items()
    }
    supplied_roles = {"callee": ["child"]}
    detached = replace(call, child_roles=supplied_roles)
    supplied_roles["callee"].clear()
    assert detached.child_roles == {"callee": ("child",)}
    with pytest.raises(TypeError):
        detached.child_roles["callee"] = ()


def _producer_concrete_kinds() -> frozenset[str]:
    node_kinds = {
        cls.__name__
        for _, cls in inspect.getmembers(producer_nodes, inspect.isclass)
        if cls.__module__ == producer_nodes.__name__ and issubclass(cls, ASTNode)
    }
    return frozenset(node_kinds | {TypeRef.__name__})


def _fact(kind: str) -> SemanticFactView:
    return SemanticFactView(
        node_id="source:for-in-target",
        node_kind=kind,
        classification="STRUCTURAL",
        resolved_type=None,
        scope_id="scope:global",
        symbol_id=None,
        overload_id=None,
        call_form=None,
        receiver_type=None,
        coercions=(),
        semantic_rule_ids=(),
        stateful_call=False,
        raw=MappingProxyType({}),
    )


def test_supported_kinds_exactly_match_installed_pine2ast_inventory() -> None:
    producer_kinds = _producer_concrete_kinds()

    assert len(producer_kinds) == 38
    assert supported_ast_kinds() == producer_kinds
    assert {"ArrayLiteral", "MapLiteral", "MatrixLiteral"}.isdisjoint(supported_ast_kinds())
    assert "ForInTarget" in supported_ast_kinds()

    target = load_reference_target_manifest()
    assert len(target.operations) == 53
    for_in_target = producer_nodes.ForInTarget(span=SourceSpan.zero(), names=["index", "value"])
    raw = for_in_target.to_dict()
    node = admit_consumer_bundle(BUNDLE_V2).ast.node_by_id[
        next(iter(admit_consumer_bundle(BUNDLE_V2).ast.node_by_id))
    ]
    structural_target = replace(
        node,
        node_id="source:for-in-target",
        kind="ForInTarget",
        fields=MappingProxyType({"names": ("index", "value")}),
        child_node_ids=(),
        child_roles=MappingProxyType({}),
    )
    recipe = select_recipe(version=6, node=structural_target, fact=_fact("ForInTarget"), call=None)
    assert raw["kind"] == "ForInTarget"
    assert recipe.opcode == "tuple.target"
    assert target.operations[recipe.opcode].evaluation == "structural"


def _create_manual_zero_to_many_plan() -> LoweringPlan:
    base = compile_consumer_bundle(BUNDLE_V6).plan
    expanded = base.dispositions[1]
    assert expanded.ir_ids
    original_ir_id = expanded.ir_ids[0]
    original = base.nodes[original_ir_id]
    extra_ir_ids = (
        "ir:sha256:" + "a" * 64,
        "ir:sha256:" + "b" * 64,
    )
    nodes = dict(base.nodes)
    nodes[extra_ir_ids[0]] = replace(original, ir_id=extra_ir_ids[0], child_ir_ids=())
    nodes[extra_ir_ids[1]] = replace(original, ir_id=extra_ir_ids[1], child_ir_ids=())
    dispositions = list(base.dispositions)
    dispositions[1] = replace(
        expanded,
        status=LoweringDispositionStatus.EXPANDED,
        ir_ids=(original_ir_id, *extra_ir_ids),
        reason="one source deliberately expands to three IR nodes",
    )
    dispositions.append(
        LoweringDisposition(
            source_node_id="source:folded",
            source_kind="Literal",
            status=LoweringDispositionStatus.FOLDED,
            ir_ids=(),
            reason="constant folded into its parent",
        )
    )
    return LoweringPlan.create(
        bundle_hash=base.bundle_hash,
        source_hash=base.source_hash,
        pine_version=base.pine_version,
        catalog_hash=base.catalog_hash,
        version_context_hash=base.version_context_hash,
        target_manifest_hash=base.target_manifest_hash,
        root_ir_id=base.root_ir_id,
        ordered_ir_ids=(*base.ordered_ir_ids, *extra_ir_ids),
        nodes=nodes,
        dispositions=tuple(dispositions),
        required_operations=base.required_operations,
        required_capabilities=base.required_capabilities,
    )


def _reseal_plan(payload: dict[str, Any]) -> dict[str, Any]:
    payload["content_hash"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_hash"}
            )
        ).hexdigest()
    )
    return payload


def test_manual_folded_and_expanded_sources_validate_with_zero_to_many_ir() -> None:
    plan = _create_manual_zero_to_many_plan()
    target = load_reference_target_manifest()

    validate_lowering_plan(plan, target)
    assert len(plan.dispositions) != len(plan.nodes)
    assert any(
        disposition.status is LoweringDispositionStatus.FOLDED and not disposition.ir_ids
        for disposition in plan.dispositions
    )
    assert any(
        disposition.status is LoweringDispositionStatus.EXPANDED and len(disposition.ir_ids) == 3
        for disposition in plan.dispositions
    )
    serialized = plan.to_dict()
    assert serialized["dispositions"] == [
        disposition.to_dict() for disposition in plan.dispositions
    ]
    assert (
        serialized["content_hash"]
        == "sha256:" + hashlib.sha256(canonical_json_bytes(plan.to_body_dict())).hexdigest()
    )


def test_plan_validator_rejects_unaccounted_and_duplicate_ir_ownership() -> None:
    plan = _create_manual_zero_to_many_plan()
    target = load_reference_target_manifest()

    unaccounted = copy.deepcopy(plan.to_dict())
    unaccounted["dispositions"][1]["ir_ids"].pop()
    with pytest.raises(BundleInvariantError, match="A2P_PLAN_IR_OWNERSHIP"):
        verify_lowering_plan_payload(_reseal_plan(unaccounted), target=target)

    duplicate = copy.deepcopy(plan.to_dict())
    duplicate["dispositions"][-1]["ir_ids"].append(duplicate["dispositions"][0]["ir_ids"][0])
    with pytest.raises(BundleInvariantError, match="A2P_PLAN_IR_OWNERSHIP"):
        verify_lowering_plan_payload(_reseal_plan(duplicate), target=target)


def test_builder_dispositions_and_ir_ids_are_deterministic_and_cryptographic() -> None:
    first = compile_consumer_bundle(BUNDLE_V6).plan
    second = compile_consumer_bundle(BUNDLE_V6).plan

    assert first.dispositions == second.dispositions
    assert first.ordered_ir_ids == second.ordered_ir_ids
    assert len(first.dispositions) == len(first.nodes)
    assert all(
        disposition.status is LoweringDispositionStatus.EMITTED and len(disposition.ir_ids) == 1
        for disposition in first.dispositions
    )
    assert all(re.fullmatch(r"ir:sha256:[0-9a-f]{64}", ir_id) for ir_id in first.ordered_ir_ids)
    assert all(
        ir_id != f"ir:{node_id}"
        for node_id, ir_id in zip(
            (disposition.source_node_id for disposition in first.dispositions),
            first.ordered_ir_ids,
            strict=True,
        )
    )


def _reseal_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    payload["content_hash"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_hash"}
            )
        ).hexdigest()
    )
    return payload


def test_projection_proof_permits_different_source_and_ir_counts() -> None:
    base = compile_consumer_bundle(BUNDLE_V6)
    plan = _create_manual_zero_to_many_plan()
    target = load_reference_target_manifest()
    emitted = emit_python_module(plan, target, module_name="zero_to_many")
    artifact = build_generated_artifact_v3(
        bundle_hash=plan.bundle_hash,
        source_hash=plan.source_hash,
        version_context=base.artifact.payload["version_context"],
        plan=plan,
        target=target,
        emitted=emitted,
        producer_commit="a" * 40,
        ast_hash=base.artifact.payload["ast_hash"],
        semantic_facts_hash=base.artifact.payload["semantic_facts_hash"],
        node_index_hash=base.artifact.payload["node_index_hash"],
    )

    verify_source_map_v2(emitted.source_map.to_dict(), expected_ir_ids=set(plan.nodes))
    verify_generated_artifact_v3(artifact.payload, plan=plan, target=target, emitted=emitted)
    proof = artifact.payload["projection_proof"]
    assert "one_to_one" not in proof
    assert proof == {
        "disposition_counts": {
            "COMPILE_TIME_ONLY": 0,
            "DELEGATED": 0,
            "EMITTED": len(base.plan.dispositions) - 1,
            "EXPANDED": 1,
            "FOLDED": 1,
            "REJECTED": 0,
        },
        "source_node_count": len(plan.dispositions),
        "ir_node_count": len(plan.nodes),
        "source_map_entry_count": len(emitted.source_map.entries),
        "mapped_ir_count": len(plan.nodes),
        "mapped_ir_coverage": True,
    }
    assert proof["source_node_count"] != proof["ir_node_count"]


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]
    "mutate",
    [
        lambda proof: proof["disposition_counts"].__setitem__(
            "FOLDED", proof["disposition_counts"]["FOLDED"] - 1
        ),
        lambda proof: proof.__setitem__("source_node_count", proof["source_node_count"] - 1),
        lambda proof: proof.__setitem__("ir_node_count", proof["ir_node_count"] - 1),
        lambda proof: proof.__setitem__(
            "source_map_entry_count", proof["source_map_entry_count"] - 1
        ),
        lambda proof: proof.__setitem__("mapped_ir_count", proof["mapped_ir_count"] - 1),
        lambda proof: proof.__setitem__("mapped_ir_coverage", False),
    ],
)
def test_projection_validator_catches_lost_disposition_ir_or_map(mutate: Any) -> None:
    result = compile_consumer_bundle(BUNDLE_V6)
    payload = copy.deepcopy(result.artifact.to_dict())
    mutate(payload["projection_proof"])

    with pytest.raises(BundleInvariantError, match="A2P_ARTIFACT_PROJECTION"):
        verify_generated_artifact_v3(
            _reseal_artifact(payload),
            plan=result.plan,
            target=load_reference_target_manifest(),
            emitted=result.emitted,
        )
