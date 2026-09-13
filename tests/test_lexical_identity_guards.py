"""Adversarial lexical identities cannot select unrelated values or ambiguous semantics."""

from dataclasses import replace
from types import MappingProxyType

import pytest

from ast2python import load_pinelib_target_manifest
from ast2python.admission.canonical import freeze_json, thaw_json
from ast2python.emission import emit_python_module
from ast2python.errors import BundleInvariantError
from tests.test_historical_forward_execution import source
from tests.test_rc6_input_metadata import compile_source


@pytest.mark.parametrize("symbol", ["pine:variable:high", "foreign:variable:close"])
def test_catalog_identity_must_belong_to_the_written_occurrence(symbol):
    result = compile_source(source(6, "plot(close)"))
    nodes = dict(result.plan.nodes)
    key = next(
        key
        for key, node in nodes.items()
        if thaw_json(node.attributes).get("fields", {}).get("name") == "close"
    )
    attributes = thaw_json(nodes[key].attributes)
    attributes["symbol_id"] = symbol
    nodes[key] = replace(nodes[key], attributes=freeze_json(attributes))
    plan = replace(result.plan, nodes=MappingProxyType(nodes))
    with pytest.raises(BundleInvariantError, match="A2P_CATALOG_OCCURRENCE"):
        emit_python_module(plan, load_pinelib_target_manifest())


@pytest.mark.parametrize("version", [1, 2])
def test_historical_builtin_before_shadow_requires_an_external_resolution_rule(version):
    with pytest.raises(BundleInvariantError, match="A2P_HISTORICAL_BINDING_AMBIGUOUS"):
        compile_source(source(version, "plot(n)\nn=7\nplot(n)"))


def test_catalog_member_cannot_select_a_different_known_value():
    result = compile_source(source(6, "plot(barstate.isfirst?1:0)"))
    nodes = dict(result.plan.nodes)
    key = next(
        key
        for key, node in nodes.items()
        if thaw_json(node.attributes).get("ast_kind") == "MemberAccessExpr"
    )
    attributes = thaw_json(nodes[key].attributes)
    attributes["symbol_id"] = "pine:variable:barstate.islast"
    nodes[key] = replace(nodes[key], attributes=freeze_json(attributes))
    with pytest.raises(BundleInvariantError, match="A2P_CATALOG_OCCURRENCE"):
        emit_python_module(
            replace(result.plan, nodes=MappingProxyType(nodes)), load_pinelib_target_manifest()
        )


def test_function_identifier_cannot_fall_back_to_its_spelling():
    from ast2python.emission.python import _DirectEmitter

    result = compile_source(source(6, "f(x)=>x\nplot(f(1))"))
    em = _DirectEmitter(result.plan, load_pinelib_target_manifest())
    nodes = dict(em.plan.nodes)
    key = next(
        key
        for key, node in nodes.items()
        if thaw_json(node.attributes).get("ast_kind") == "Identifier"
        and thaw_json(node.attributes).get("fields", {}).get("name") == "f"
    )
    attributes = thaw_json(nodes[key].attributes)
    attributes["symbol_id"] = "user:function:f:n99999999"
    nodes[key] = replace(nodes[key], attributes=freeze_json(attributes))
    em.plan = replace(em.plan, nodes=MappingProxyType(nodes))
    with pytest.raises(BundleInvariantError):
        em._identifier(key)


def test_foreign_local_declaration_is_not_visible_to_a_global_occurrence():
    result = compile_source(source(6, "x=1\nif true\n    x=2\nplot(x)"))
    nodes = dict(result.plan.nodes)
    rows = {key: thaw_json(node.attributes) for key, node in nodes.items()}
    inner = next(
        row
        for row in rows.values()
        if row.get("ast_kind") == "VarDeclaration"
        and row.get("fields", {}).get("name") == "x"
        and row.get("scope_id") != "scope:global"
    )
    key = next(
        key
        for key, row in rows.items()
        if row.get("ast_kind") == "Identifier"
        and row.get("fields", {}).get("name") == "x"
        and row.get("scope_id") == "scope:global"
    )
    rows[key]["symbol_id"] = inner["symbol_id"]
    nodes[key] = replace(nodes[key], attributes=freeze_json(rows[key]))
    with pytest.raises(BundleInvariantError, match="A2P_LEXICAL_BINDING_SCOPE"):
        emit_python_module(
            replace(result.plan, nodes=MappingProxyType(nodes)), load_pinelib_target_manifest()
        )
