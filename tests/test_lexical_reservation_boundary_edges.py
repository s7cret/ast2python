"""Defensive IR boundary checks after real admission; not TradingView oracles."""

from dataclasses import replace
from types import MappingProxyType

import pytest

from ast2python import load_pinelib_target_manifest
from ast2python.admission.canonical import freeze_json
from ast2python.emission.lexical import identifier_local, prepare_lexical_names, written_name
from ast2python.emission.ordering import prepare_historical_series
from ast2python.emission.python import _DirectEmitter
from ast2python.errors import BundleInvariantError
from ast2python.lowering.history_reservation import CAPABILITY, OPERATION
from tests.test_historical_forward_execution import compile_source, source


def emitter(body="x=close\nplot(x)", version=6):
    result = compile_source(source(version, body))
    return _DirectEmitter(result.plan, load_pinelib_target_manifest())


def identifier(em, name):
    return next(
        key
        for key in em.plan.ordered_ir_ids
        if em._attrs(key).get("ast_kind") == "Identifier" and em._fields(key).get("name") == name
    )


def attributes(em, key, **changes):
    attrs = em._attrs(key)
    attrs.update(changes)
    nodes = dict(em.plan.nodes)
    nodes[key] = replace(nodes[key], attributes=freeze_json(attrs))
    em.plan = replace(em.plan, nodes=MappingProxyType(nodes))


@pytest.mark.parametrize("symbol", [None, "user:vardeclaration:x:absent"])
def test_missing_or_unbound_occurrence_identity_is_rejected(symbol):
    em = emitter()
    key = identifier(em, "x")
    attributes(em, key, symbol_id=symbol)
    with pytest.raises(BundleInvariantError, match="A2P_LEXICAL_BINDING_IDENTITY"):
        identifier_local(em, key)


def test_known_declaration_identity_cannot_be_used_with_a_different_name():
    em = emitter()
    key = identifier(em, "x")
    attributes(em, key, fields={"name": "other"})
    with pytest.raises(BundleInvariantError, match="A2P_LEXICAL_BINDING_IDENTITY"):
        identifier_local(em, key)


def test_declaration_identity_must_match_its_owner_node():
    em = emitter()
    key = next(
        key for key in em.plan.ordered_ir_ids if em._attrs(key).get("ast_kind") == "VarDeclaration"
    )
    attributes(em, key, symbol_id="user:vardeclaration:x:foreign")
    with pytest.raises(BundleInvariantError, match="A2P_LEXICAL_BINDING_IDENTITY"):
        prepare_lexical_names(em)


@pytest.mark.parametrize("owners", [0, 2])
def test_implicit_storage_requires_one_owner_scope(owners):
    em = emitter()
    key = identifier(em, "x")
    local = em.lexical_names[em._attrs(key)["symbol_id"]][1]
    del em.declarations_by_py[local]
    em.local_names = {(f"scope:owner{i}", "x"): local for i in range(owners)}
    with pytest.raises(BundleInvariantError, match="A2P_LEXICAL_BINDING_SCOPE"):
        identifier_local(em, key)


def test_cyclic_scope_ancestry_cannot_hang_identifier_resolution():
    em = emitter()
    key = identifier(em, "x")
    attributes(em, key, scope_id="scope:cycle")
    em.scope_parents = {"scope:cycle": "scope:cycle"}
    with pytest.raises(BundleInvariantError, match="A2P_LEXICAL_BINDING_SCOPE"):
        identifier_local(em, key)


def test_new_identity_transport_also_works_in_reference_component_mode():
    em = emitter()
    key = identifier(em, "x")
    expected = em.lexical_names[em._attrs(key)["symbol_id"]][1]
    em.exact_pinelib = False
    assert identifier_local(em, key) == expected


def test_catalog_snapshot_must_match_the_admitted_hash():
    em = emitter()
    key = identifier(em, "close")
    em.plan = replace(em.plan, catalog_hash="sha256:" + "0" * 64)
    with pytest.raises(BundleInvariantError, match="A2P_CATALOG_OCCURRENCE"):
        identifier_local(em, key)


@pytest.mark.parametrize("shape", ["missing_object", "cycle", "non_member"])
def test_static_catalog_path_rejects_malformed_or_cyclic_ir(shape):
    em = emitter("plot(barstate.isfirst?1:0)")
    key = next(
        key
        for key in em.plan.ordered_ir_ids
        if em._attrs(key).get("ast_kind") == "MemberAccessExpr"
    )
    assert written_name(em, key) == "barstate.isfirst"
    if shape == "non_member":
        attributes(em, key, ast_kind="Literal")
    else:
        attributes(em, key, child_roles={"object": [key] if shape == "cycle" else []})
    with pytest.raises(BundleInvariantError, match="A2P_CATALOG_OCCURRENCE"):
        written_name(em, key)


def test_implicit_loop_binder_cannot_emit_without_storage():
    em = emitter("x=0\nfor i=0 to 1\n    x:=x+i\nplot(x)")
    em.local_names = {}
    with pytest.raises(BundleInvariantError, match="A2P_LEXICAL_BINDING_IDENTITY"):
        prepare_lexical_names(em)


def test_callable_component_uses_exact_id_and_checks_written_name():
    em = emitter("f(x)=>x\nplot(f(1))")
    key = identifier(em, "f")
    symbol, declaration = next(iter(em.callable_declarations.items()))
    attributes(em, key, symbol_id=symbol)
    assert em._identifier(key) == f"self.{em.callable_names[declaration]}"
    attributes(em, key, fields={"name": "other"})
    with pytest.raises(BundleInvariantError, match="A2P_LEXICAL_BINDING_IDENTITY"):
        em._identifier(key)


@pytest.mark.parametrize("corruption", ["opcode", "capability", "operation", "owner", "storage"])
def test_reservation_emission_revalidates_owned_plan_and_storage(corruption):
    em = emitter("b=close\na=b[1]", version=2)
    (key,) = em._role(em.plan.root_ir_id, "history_reservations")
    owner = em._fields(key)["declaration_ir_id"]
    if corruption == "opcode":
        nodes = dict(em.plan.nodes)
        nodes[key] = replace(nodes[key], opcode="foreign.reservation")
        em.plan = replace(em.plan, nodes=MappingProxyType(nodes))
    elif corruption == "capability":
        em.plan = replace(
            em.plan, required_capabilities=em.plan.required_capabilities - {CAPABILITY}
        )
    elif corruption == "operation":
        em.plan = replace(em.plan, required_operations=em.plan.required_operations - {OPERATION})
    elif corruption == "owner":
        fields = em._fields(key)
        fields["declaration_ir_id"] = "missing-owner"
        attributes(em, key, fields=fields)
    else:
        em.series_ids = {}
    with pytest.raises(BundleInvariantError, match="A2P_HISTORY_RESERVATION_PLAN"):
        prepare_historical_series(em, (owner,))
