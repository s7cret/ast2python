"""Independent structural expectations for input active-expression metadata."""

from dataclasses import replace

import pytest

from ast2python.emission.metadata import ScriptMetadata
from ast2python.errors import BundleInvariantError
from tests.stage4.test_emitter_boundary_edges import Graph


def metadata(graph):
    return ScriptMetadata(replace(graph.emitter.plan, ordered_ir_ids=()))


@pytest.mark.parametrize(
    "op,name",
    [
        ("+", "add"),
        ("-", "sub"),
        ("*", "mul"),
        ("/", "div"),
        ("%", "mod"),
        ("and", "and"),
        ("or", "or"),
        ("==", "eq"),
        ("!=", "ne"),
        ("<", "lt"),
        ("<=", "le"),
        (">", "gt"),
        (">=", "ge"),
    ],
)
def test_binary_active_preserves_operator_and_operand_order(op, name):
    g = Graph()
    left, right = g.literal(7), g.literal(2)
    key = g.add("BinaryExpr", {"op": op}, roles={"left": [left], "right": [right]})
    assert metadata(g).active_value(key) == {
        "op": name,
        "left": {"op": "literal", "value": 7},
        "right": {"op": "literal", "value": 2},
    }


def test_conditional_active_preserves_all_three_branches():
    g = Graph()
    cond, yes, no = g.literal(False), g.literal(7), g.literal(2)
    key = g.add("ConditionalExpr", roles={"condition": [cond], "if_true": [yes], "if_false": [no]})
    assert metadata(g).active_value(key) == {
        "op": "if",
        "condition": {"op": "literal", "value": False},
        "then": {"op": "literal", "value": 7},
        "else": {"op": "literal", "value": 2},
    }


@pytest.mark.parametrize("value", [True, 7, 2.5, "checked"])
def test_producer_constant_fallback_retains_literal_type(value):
    g = Graph()
    key = g.add("Identifier", {"name": "constant"}, const_value=value)
    expected = True if value is True else {"op": "literal", "value": value}
    assert metadata(g).active_value(key) == expected


def test_enum_active_keeps_exact_nominal_identity():
    g = Graph()
    owner = g.add("Identifier", {"name": "Choice"})
    key = g.add("MemberAccessExpr", {"member": "first"}, roles={"object": [owner]})
    data = metadata(g)
    marker = {"$pinelib_enum": {"enum_id": "enum:choice", "member": "first", "ordinal": 0}}
    data.enum_members[("Choice", "first")] = marker
    assert data.active_value(key) == {"op": "literal", "value": marker}


@pytest.mark.parametrize("op,name", [("not", "not"), ("+", "pos"), ("-", "neg")])
def test_unary_active_retains_operator(op, name):
    g = Graph()
    value = g.literal(3)
    key = g.add("UnaryExpr", {"op": op}, roles={"operand": [value]})
    assert metadata(g).active_value(key) == {"op": name, "arg": {"op": "literal", "value": 3}}


def test_active_cycle_fails_closed():
    g = Graph()
    key = g.literal(True)
    with pytest.raises(BundleInvariantError, match="cyclic active metadata"):
        metadata(g).active_value(key, visiting=frozenset({key}))


def test_non_scalar_active_literal_fails_closed():
    g = Graph()
    key = g.add("Literal", {"value": None, "literal_type": "na"})
    with pytest.raises(BundleInvariantError, match="not an admitted scalar"):
        metadata(g).active_value(key)
