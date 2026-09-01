from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from ast2python import BundleInvariantError, load_reference_target_manifest
from ast2python import compile_reference_consumer_bundle as compile_consumer_bundle
from ast2python.admission.canonical import freeze_json, thaw_json
from ast2python.emission.python import _DirectEmitter

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "consumer" / "pine-v6-consumer-bundle.json"
)


def _mutated_emitter(
    *,
    kind: str,
    fields: dict[str, Any] | None = None,
    child_roles: dict[str, list[str]] | None = None,
    drop_value_bindings: bool = False,
) -> tuple[_DirectEmitter, str]:
    result = compile_consumer_bundle(FIXTURE)
    ir_id = result.plan.ordered_ir_ids[-1]
    node = result.plan.nodes[ir_id]
    attributes = thaw_json(node.attributes)
    attributes["ast_kind"] = kind
    attributes["fields"] = fields or {}
    attributes["child_roles"] = child_roles or {}
    nodes = dict(result.plan.nodes)
    nodes[ir_id] = replace(
        node,
        attributes=freeze_json(attributes),
        child_ir_ids=tuple(
            child for children in (child_roles or {}).values() for child in children
        ),
    )
    plan = replace(result.plan, nodes=MappingProxyType(nodes))
    target = load_reference_target_manifest()
    if drop_value_bindings:
        target = replace(target, value_bindings=MappingProxyType({}))
    return _DirectEmitter(plan, target), ir_id


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("Argument", "A2P_EMIT_ARGUMENT"),
        ("BinaryExpr", "A2P_EMIT_BINARY"),
        ("UnaryExpr", "A2P_EMIT_UNARY"),
        ("ConditionalExpr", "A2P_EMIT_CONDITIONAL"),
        ("HistoryRefExpr", "A2P_EMIT_HISTORY"),
        ("UnknownExpr", "A2P_EMIT_EXPRESSION"),
    ],
)
def test_expression_shapes_fail_closed(kind: str, code: str) -> None:
    emitter, ir_id = _mutated_emitter(kind=kind)
    with pytest.raises(BundleInvariantError, match=code):
        emitter._expr(ir_id)


def test_call_without_producer_facts_fails_closed() -> None:
    emitter, ir_id = _mutated_emitter(kind="CallExpr")
    with pytest.raises(BundleInvariantError, match="A2P_EMIT_CALL"):
        emitter._expr(ir_id)


def test_member_access_without_exact_value_binding_fails_closed() -> None:
    emitter, ir_id = _mutated_emitter(
        kind="MemberAccessExpr",
        drop_value_bindings=True,
    )
    with pytest.raises(BundleInvariantError, match="A2P_EMIT_VALUE_BINDING"):
        emitter._expr(ir_id)


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("VarDeclaration", "A2P_EMIT_VAR"),
        ("Reassignment", "A2P_EMIT_ASSIGNMENT"),
        ("UnknownStatement", "A2P_EMIT_STATEMENT"),
    ],
)
def test_statement_shapes_fail_closed(kind: str, code: str) -> None:
    emitter, ir_id = _mutated_emitter(kind=kind)
    with pytest.raises(BundleInvariantError, match=code):
        emitter._emit_statement(ir_id)


def test_empty_block_and_empty_function_emit_structurally() -> None:
    block_emitter, block_ir = _mutated_emitter(kind="Block", child_roles={"statements": []})
    block_emitter._emit_block(block_ir)
    assert block_emitter.writer.lines[-1].strip() == "pass"

    function_emitter, function_ir = _mutated_emitter(
        kind="FunctionDeclaration",
        fields={"name": "empty"},
        child_roles={"parameters": [], "body": []},
    )
    function_emitter.functions_by_name["empty"] = "udf_empty"
    function_emitter._emit_function(function_ir)
    assert any("def udf_empty" in line for line in function_emitter.writer.lines)
    assert any("return None" in line for line in function_emitter.writer.lines)


def test_identifier_and_helper_defensive_paths() -> None:
    emitter, ir_id = _mutated_emitter(
        kind="Identifier",
        fields={"name": "missing"},
        drop_value_bindings=True,
    )
    with pytest.raises(BundleInvariantError, match="A2P_EMIT_VALUE_BINDING"):
        emitter._identifier(ir_id)
    safe_name = emitter._safe("class", "value", "id")
    assert safe_name.isidentifier()
    assert safe_name != "class"
    assert emitter._roles(ir_id) == {}
    assert emitter._lookup_local("missing", "missing") is None
