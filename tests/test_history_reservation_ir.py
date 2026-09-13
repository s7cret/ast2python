"""Reservation lowering owns its operation, dependencies and source mapping."""

import ast
from dataclasses import replace

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle

from ast2python import compile_reference_consumer_bundle
from ast2python.admission.canonical import freeze_json, thaw_json
from ast2python.emission import emit_python_module
from ast2python.errors import BundleInvariantError
from ast2python.lowering import validate_lowering_plan
from ast2python.lowering.history_plan import expand_history_reservations
from ast2python.lowering.model import LoweringPlan
from tests.test_history_reservation_contract import admit, target_source


def lexical_plan(target):
    """Component fixture carrying the agreed producer declaration identities."""
    bundle = build_consumer_bundle(
        '//@version=2\nstudy("reservation")\nb=close\na=b[1]\n', producer_commit="1" * 40
    )
    plan = compile_reference_consumer_bundle(bundle, expected_pine2ast_commit="1" * 40).plan
    attributes = {key: thaw_json(node.attributes) for key, node in plan.nodes.items()}
    symbols = {
        row["fields"]["name"]: row["symbol_id"]
        for row in attributes.values()
        if row["ast_kind"] == "VarDeclaration"
    }
    for row in attributes.values():
        if row["ast_kind"] == "Identifier" and row["fields"]["name"] in symbols:
            row["symbol_id"] = symbols[row["fields"]["name"]]
    kwargs = {
        name: getattr(plan, name)
        for name in (
            "bundle_hash",
            "source_hash",
            "pine_version",
            "catalog_hash",
            "version_context_hash",
            "root_ir_id",
            "ordered_ir_ids",
            "dispositions",
            "required_operations",
            "required_capabilities",
        )
    }
    return LoweringPlan.create(
        **kwargs,
        target_manifest_hash=target.content_hash,
        nodes={
            key: replace(node, attributes=freeze_json(attributes[key]))
            for key, node in plan.nodes.items()
        },
    )


def test_reservation_is_owned_ir_not_raw_state_write(tmp_path):
    target = admit(tmp_path, target_source())
    original = lexical_plan(target)
    plan = expand_history_reservations(original, target)
    validate_lowering_plan(plan, target)
    assert "state.reserve_history.v1" in plan.required_operations
    assert "compiler.history_reservation.v1" in plan.required_capabilities
    reserves = [row for row in plan.nodes.values() if row.opcode == "state.reserve_history.v1"]
    assert len(reserves) == 1
    owners = [row for row in plan.dispositions if reserves[0].ir_id in row.ir_ids]
    assert len(owners) == 1 and owners[0].status.value == "EXPANDED"
    assert len(plan.nodes) == len(original.nodes) + 1
    emitted = emit_python_module(plan, target)
    assert ".set_series(" not in emitted.code
    tree = ast.parse(emitted.code)
    aliases = {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "pinelib.abi.primitives"
        for alias in node.names
        if alias.name == "reserve_history_v1"
    }
    assert len(aliases) == 1
    assert (
        sum(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in aliases
            for node in ast.walk(tree)
        )
        == 1
    )


def test_old_target_cannot_reserve_history_by_method_presence(tmp_path):
    raw = target_source()
    del raw["compiled_history_reservation"]
    raw["compiler_operations"].pop()
    target = admit(tmp_path, raw)
    assert "compiler.history_reservation.v1" not in target.capabilities
    with pytest.raises(BundleInvariantError, match="A2P_HISTORY_RESERVATION_CONTRACT"):
        expand_history_reservations(lexical_plan(target), target)
