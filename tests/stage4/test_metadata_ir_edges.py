"""Metadata extraction from synthetic checked-IR shapes, without source reparsing."""

from dataclasses import replace

import pytest

from ast2python.emission.metadata import ScriptMetadata
from ast2python.errors import BundleInvariantError
from tests.stage4.test_emitter_boundary_edges import Graph


def input_metadata(symbol, values):
    graph = Graph()
    arguments, bindings = [], []
    for index, (name, value) in enumerate(values.items()):
        if isinstance(value, tuple) and value[0] == "symbol":
            target = graph.add(
                "Identifier", {"name": value[1]}, symbol_id="pine:variable:" + value[1]
            )
        else:
            target = graph.literal(value)
        argument = graph.add("Argument", roles={"value": [target]})
        arguments.append(argument)
        bindings.append(
            {
                "argument_node_id": graph.emitter._node(argument).source.node_id,
                "parameter_index": index,
                "parameter_name": name,
            }
        )
    root = graph.add(
        "CallExpr",
        roles={"arguments": arguments},
        call={"symbol_id": symbol, "arguments": bindings},
    )
    plan = replace(graph.emitter.plan, ordered_ir_ids=(root,))
    return ScriptMetadata(plan)


@pytest.mark.parametrize(
    "values,kind,default",
    [
        ({"defval": 1, "type": ("symbol", "input.integer")}, "int", 1),
        ({"defval": "S", "type": ("symbol", "input.symbol")}, "symbol", "S"),
        ({"defval": ("symbol", "close")}, "source", "close"),
        ({"defval": False}, "bool", False),
        ({"defval": 1.5}, "float", 1.5),
    ],
)
def test_legacy_input_kind_is_explicit_or_from_its_admitted_default(values, kind, default):
    metadata = input_metadata("pine:function:input", values)
    assert len(metadata.inputs) == 1
    descriptor = next(iter(metadata.inputs.values()))
    assert descriptor["kind"] == kind and descriptor["default"] == default


@pytest.mark.parametrize(
    "symbol,values,message",
    [
        ("pine:function:input.int", {}, "lacks an admitted default"),
        ("pine:function:input.int", {"defval": 1, "unknown": 2}, "unsupported metadata"),
        ("pine:function:input", {"defval": 1, "type": 7}, "admitted input constant"),
        ("pine:function:input", {"defval": 1, "type": "wrong"}, "admitted input constant"),
        ("pine:function:input", {"defval": 1, "type": "input.unknown"}, "kind is not supported"),
        ("pine:function:input", {"defval": None}, "kind is not supported"),
        ("pine:function:input.unknown", {"defval": 1}, "kind is not supported"),
    ],
)
def test_input_metadata_rejects_unsupported_or_incomplete_shapes(symbol, values, message):
    with pytest.raises(BundleInvariantError, match=message):
        input_metadata(symbol, values)


def test_script_declaration_requires_one_checked_call():
    graph = Graph()
    root = graph.add("DeclarationStatement", {"script_type": "indicator"})
    with pytest.raises(BundleInvariantError, match="script declaration is incomplete"):
        ScriptMetadata(replace(graph.emitter.plan, ordered_ir_ids=(root,)))


def test_argument_metadata_requires_producer_node_identity():
    graph = Graph()
    root = graph.add(
        "CallExpr",
        call={
            "symbol_id": "pine:function:input.int",
            "arguments": [
                {"parameter_index": 0, "parameter_name": "defval", "argument_node_id": "absent"}
            ],
        },
    )
    with pytest.raises(BundleInvariantError, match="exact producer binding"):
        ScriptMetadata(replace(graph.emitter.plan, ordered_ir_ids=(root,)))


def test_tuple_constants_and_symbolic_runtime_constants_remain_distinct():
    graph = Graph()
    first, second = graph.literal(7), graph.literal(False)
    pair = graph.add("TupleExpr", roles={"elements": [first, second]})
    symbolic = graph.add("MemberAccessExpr", symbol_id="pine:variable:currency.USD")
    metadata = ScriptMetadata(replace(graph.emitter.plan, ordered_ir_ids=()))
    assert metadata.constant(pair) == [7, False]
    assert metadata.constant(symbolic) == "currency.USD"
    assert metadata.source_name(symbolic) is None
    with pytest.raises(BundleInvariantError, match="cyclic constant metadata"):
        metadata.constant(first, visiting=frozenset({first}))


@pytest.mark.parametrize("mode", ["resolved", "missing", "cycle"])
def test_constant_declarations_require_real_initializer_and_acyclic_identity(mode):
    graph = Graph()
    ref = graph.add(
        "Identifier",
        {"name": "metadata_edge"},
        symbol_id="user:variable:metadata_edge",
        const_value=None,
    )
    initializers = [] if mode == "missing" else [ref] if mode == "cycle" else [graph.literal(17)]
    graph.add(
        "VarDeclaration",
        {"name": "metadata_edge"},
        {"initializer": initializers},
        symbol_id="user:variable:metadata_edge",
        const_value=None,
    )
    metadata = ScriptMetadata(replace(graph.emitter.plan, ordered_ir_ids=()))
    if mode == "resolved":
        assert metadata.constant(ref) == 17
    else:
        with pytest.raises(BundleInvariantError, match="A2P_STATIC_METADATA"):
            metadata.constant(ref)


def test_unknown_constant_does_not_become_a_guessed_value():
    graph = Graph()
    unknown = graph.add(
        "Identifier", {"name": "unknown"}, symbol_id="user:variable:unknown", const_value=None
    )
    metadata = ScriptMetadata(replace(graph.emitter.plan, ordered_ir_ids=()))
    with pytest.raises(BundleInvariantError, match="no admitted constant value"):
        metadata.constant(unknown)
