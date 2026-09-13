"""Component-level emitter guards on explicit synthetic IR, not Pine parity oracles."""

import ast
from dataclasses import replace
from types import MappingProxyType

import pytest

from ast2python.admission.canonical import freeze_json, thaw_json
from ast2python.emission.python import _imports_from_code
from ast2python.errors import BundleInvariantError
from tests.stage4.test_direct_emitter_defensive import _mutated_emitter


class Graph:
    """Extend the existing real reference-compiler fixture for emitter unit tests."""

    def __init__(self):
        self.emitter, self.template_id = _mutated_emitter(kind="Literal", fields={"value": 0})

    def add(self, kind, fields=None, roles=None, **extra):
        emitter = self.emitter
        nodes = dict(emitter.plan.nodes)
        key = f"edge:{len(nodes)}"
        template = nodes[self.template_id]
        attrs = thaw_json(template.attributes)
        attrs.update(
            ast_kind=kind,
            fields=fields or {},
            child_roles=roles or {},
            scope_id="scope:global",
            symbol_id=None,
        )
        attrs.update(extra)
        children = tuple(child for group in (roles or {}).values() for child in group)
        nodes[key] = replace(
            template,
            ir_id=key,
            attributes=freeze_json(attrs),
            child_ir_ids=children,
            source=replace(template.source, node_id="source:" + key),
        )
        emitter.plan = replace(emitter.plan, nodes=MappingProxyType(nodes))
        emitter.writer.plan = emitter.plan
        return key

    def literal(self, value):
        return self.add("Literal", {"value": value})


def test_subtree_deduplicates_cycles_and_ignores_missing_edges():
    graph = Graph()
    key = graph.literal(1)
    em = graph.emitter
    nodes = dict(em.plan.nodes)
    nodes[key] = replace(nodes[key], child_ir_ids=(key, "absent", key))
    em.plan = replace(em.plan, nodes=MappingProxyType(nodes))
    assert em._subtree(key) == (key,)


def test_reference_identifier_preserves_function_binding_and_rejects_unbound_na():
    graph = Graph()
    em = graph.emitter
    em.functions_by_name["f"] = "udf_f"
    assert em._identifier(graph.add("Identifier", {"name": "f"})) == "self.udf_f"
    em.target = replace(em.target, value_bindings=MappingProxyType({}))
    with pytest.raises(BundleInvariantError, match="A2P_NA_UNSUPPORTED_FAIL_CLOSED"):
        em._identifier(graph.add("Identifier", {"name": "na"}))


def test_legacy_series_identity_respects_local_binding_and_builtin_identity():
    graph = Graph()
    em = graph.emitter
    assert em._legacy_series_identity(graph.literal(1)) is None
    em.local_names[("scope:global", "edge_capture_x")] = "var_x"
    em.scalar_declarations["var_x"] = ("series:x", "default", "float")
    assert (
        em._legacy_series_identity(
            graph.add(
                "Identifier", {"name": "edge_capture_x"}, symbol_id="user:variable:edge_capture_x"
            )
        )
        == "series:x"
    )
    assert (
        em._legacy_series_identity(
            graph.add("Identifier", {"name": "close"}, symbol_id="pine:variable:close")
        )
        == "close"
    )
    assert (
        em._legacy_series_identity(
            graph.add("Identifier", {"name": "unknown"}, symbol_id="user:variable:unknown")
        )
        is None
    )


@pytest.mark.parametrize("operator,expected", [("and", False), ("or", True)])
def test_reference_boolean_operations_are_python_short_circuit_expressions(operator, expected):
    graph = Graph()
    left, right = graph.literal(False), graph.literal(True)
    root = graph.add("BinaryExpr", {"op": operator}, {"left": [left], "right": [right]})
    expression = graph.emitter._expr(root)
    assert isinstance(ast.parse(expression, mode="eval").body, ast.BoolOp)
    assert eval(expression, {"__builtins__": {}}) is expected
    argument = graph.add("Argument", roles={"value": [right]})
    assert graph.emitter._expr(argument) == "True"


@pytest.mark.parametrize("selector", [False, True])
def test_legacy_switch_expression_preserves_case_and_default(selector):
    graph = Graph()
    condition, first, otherwise = graph.literal(True), graph.literal(7), graph.literal(9)
    case = graph.add("SwitchCase", roles={"condition": [condition], "body": [first]})
    fallback = graph.add("SwitchCase", roles={"body": [otherwise]})
    root = graph.add(
        "SwitchStructure",
        roles={"expression": [condition] if selector else [], "cases": [case, fallback]},
    )
    expression = graph.emitter._switch_expression(root)
    assert eval(expression, {"__builtins__": {"bool": bool}}) == 7


@pytest.mark.parametrize(
    "malformation", ["selectors", "empty", "body", "conditions", "block", "defaults"]
)
def test_legacy_switch_rejects_malformed_shape(malformation):
    graph = Graph()
    value = graph.literal(1)
    body = graph.add("Block") if malformation == "block" else value
    roles = {"body": [] if malformation == "body" else [body]}
    if malformation == "conditions":
        roles["condition"] = [value, value]
    case = graph.add("SwitchCase", roles=roles)
    cases = (
        [] if malformation == "empty" else [case, case] if malformation == "defaults" else [case]
    )
    root = graph.add(
        "SwitchStructure",
        roles={"cases": cases, "expression": [value, value] if malformation == "selectors" else []},
    )
    with pytest.raises(BundleInvariantError, match="A2P_EMIT_SWITCH"):
        graph.emitter._switch_expression(root)


@pytest.mark.parametrize("kind", ["ForInStructure", "WhileStructure", "Block"])
def test_reference_statement_forms_emit_executable_bounded_python(kind):
    graph = Graph()
    body = graph.add("Block", roles={"statements": []})
    if kind == "ForInStructure":
        target = graph.add("TupleTarget", {"names": ["item"]})
        iterable = graph.literal([1, 2])
        root = graph.add(kind, roles={"target": [target], "iterable": [iterable], "body": [body]})
    elif kind == "WhileStructure":
        root = graph.add(kind, roles={"condition": [graph.literal(False)], "body": [body]})
    else:
        root = body
    graph.emitter._emit_statement(root)
    code = graph.emitter.writer.render()
    ast.parse(code)
    exec(code, {"__builtins__": {"bool": bool}})


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"supported_pine_versions": (1,)}, "A2P_PINELIB_VALUE_VERSION"),
        (
            {"disposition": "REFERENCE_RUNTIME_ATTRIBUTE", "python_name": None},
            "A2P_EMIT_VALUE_BINDING",
        ),
        (
            {"disposition": "TARGET_DELEGATED", "delegation_owner": None},
            "A2P_PINELIB_VALUE_DELEGATION",
        ),
        ({"disposition": "UNSUPPORTED"}, "A2P_PINELIB_VALUE_UNSUPPORTED"),
        ({"disposition": "TARGET_DIRECT", "python_module": None}, "A2P_PINELIB_VALUE_CALLABLE"),
    ],
)
def test_corrupt_runtime_value_binding_never_falls_back(updates, code):
    graph = Graph()
    value = next(iter(graph.emitter.target.value_bindings.values()))
    with pytest.raises(BundleInvariantError, match=code):
        graph.emitter._value(graph.template_id, replace(value, **updates))


@pytest.mark.parametrize("kind", ["ABI_DEFAULT", "UNBOUND_FAIL_CLOSED"])
def test_direct_value_abi_defaults_and_explicit_unbound_are_distinct(kind):
    graph = Graph()
    em = graph.emitter
    value = next(iter(em.target.value_bindings.values()))
    value = replace(
        value,
        disposition="TARGET_DIRECT",
        python_module="runtime_values",
        python_name="read",
        parameter_bindings=({"binding": kind, "abi_parameter": "parameter"},),
    )
    em.direct_value_aliases[value.symbol_id] = "read"
    if kind == "ABI_DEFAULT":
        assert em._value(graph.template_id, value) == "read()"
    else:
        with pytest.raises(BundleInvariantError, match="A2P_PINELIB_UNBOUND_VALUE_PARAMETER"):
            em._value(graph.template_id, value)


def test_import_inventory_keeps_both_import_forms_and_deduplicates():
    assert _imports_from_code("import alpha, beta\nfrom alpha import thing\n") == ("alpha", "beta")


def configured_call(graph, **overrides):
    """Mutate post-admission binding state to exercise emitter defense in depth."""
    em = graph.emitter
    original = next(
        binding
        for binding in em.target.call_bindings.values()
        if em.plan.pine_version in binding.supported_pine_versions
    )
    changes = dict(
        parameters=(),
        parameter_qualifiers={},
        parameter_bindings=(),
        disposition="TARGET_DIRECT",
        python_module="runtime_calls",
        python_name="call",
    )
    changes.update(overrides)
    binding = replace(original, **changes)
    em.target = replace(em.target, call_bindings=MappingProxyType({binding.key: binding}))
    em.exact_pinelib = True
    em.direct_call_aliases[binding.key] = "call_target"
    node = graph.add(
        "CallExpr",
        call={
            "symbol_id": binding.symbol_id,
            "overload_id": binding.overload_id,
            "call_form": binding.call_form,
            "arguments": [],
        },
    )
    return em, node, binding


@pytest.mark.parametrize(
    "row,code",
    [
        ({"binding": "METHOD_RECEIVER", "abi_parameter": "x"}, "A2P_PINELIB_METHOD_RECEIVER"),
        ({"binding": "UNKNOWN", "abi_parameter": "x"}, "A2P_PINELIB_PARAMETER_BINDING"),
        (
            {"binding": "INJECTED", "source": "UNKNOWN", "abi_parameter": "x"},
            "A2P_PINELIB_INJECTION",
        ),
        (
            {"binding": "INJECTED", "source": "SEMANTIC_TYPE_DESCRIPTOR", "abi_parameter": "x"},
            "A2P_PINELIB_TYPE_DESCRIPTOR",
        ),
        (
            {"binding": "INJECTED", "source": "REQUEST_TIMEFRAME_ARGUMENT", "abi_parameter": "x"},
            "A2P_REQUEST_TIMEFRAME",
        ),
    ],
)
def test_exact_call_rejects_incomplete_post_admission_binding(row, code):
    em, node, _ = configured_call(Graph(), parameter_bindings=(row,))
    with pytest.raises(BundleInvariantError, match=code):
        em._call(node)


def test_exact_call_requires_the_import_it_declares():
    em, node, _ = configured_call(Graph())
    em.direct_call_aliases.clear()
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_CALLABLE"):
        em._call(node)


def test_semantic_return_type_injection_uses_binding_metadata():
    em, node, _ = configured_call(
        Graph(),
        return_type="float",
        parameter_bindings=(
            {"binding": "INJECTED", "source": "SEMANTIC_RETURN_TYPE", "abi_parameter": "kind"},
        ),
    )
    assert em._call(node) == "call_target(kind='float')"


def test_delegated_call_rejects_incomplete_identity():
    em, node, _ = configured_call(Graph(), disposition="TARGET_DELEGATED", delegation_owner=None)
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_CALL_DELEGATION"):
        em._call(node)


def test_delegated_value_is_not_a_dispatch_receipt_and_void_preserves_receiver():
    from ast2python.lowering.model import IRType

    graph = Graph()
    em, node, _ = configured_call(
        graph,
        disposition="TARGET_DELEGATED",
        delegation_owner="backtest-engine",
        delegation_schema_id="openpine.backtest.engine.v1",
        delegation_capability_id="strategy.cancel_all",
    )
    nodes = dict(em.plan.nodes)
    nodes[node] = replace(nodes[node], result_type=IRType("float", "series", False))
    em.plan = replace(em.plan, nodes=MappingProxyType(nodes))
    with pytest.raises(BundleInvariantError, match="A2P_DELEGATED_RESULT_REQUIRES_COMMIT"):
        em._call(node)
    receiver = graph.literal(9)
    nodes = dict(em.plan.nodes)
    attrs = thaw_json(nodes[node].attributes)
    attrs["child_roles"] = {"receiver": [receiver]}
    nodes[node] = replace(
        nodes[node],
        result_type=IRType("void", "series", False),
        attributes=freeze_json(attrs),
        child_ir_ids=(receiver,),
    )
    em.plan = replace(em.plan, nodes=MappingProxyType(nodes))
    code = em._call(node)
    assert "owner='backtest-engine'" in code
    assert "'positional': [9]" in code
    ast.parse(code, mode="eval")


def test_exact_primitive_requires_module_and_valid_argument_index():
    graph = Graph()
    em = graph.emitter
    opcode, operation = next(iter(em.target.operations.items()))
    em.exact_pinelib = True
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_PRIMITIVE_MISSING"):
        em._runtime_operation(opcode)
    operation = replace(
        operation,
        python_module="runtime_ops",
        parameter_bindings=({"binding": "OPERATION_ARGUMENT", "source_index": 1},),
    )
    em.target = replace(em.target, operations=MappingProxyType({opcode: operation}))
    em.direct_operation_aliases[opcode] = "primitive"
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_PRIMITIVE_BINDING"):
        em._runtime_operation(opcode, "only_argument")


@pytest.mark.parametrize(
    "runtime_module,code",
    [
        ("ast2python", "A2P_EMIT_FORBIDDEN_IMPORT"),
        ("unapproved_runtime", "A2P_EMIT_IMPORT"),
    ],
)
def test_emitted_imports_are_checked_even_after_target_admission(runtime_module, code):
    from ast2python import load_pinelib_target_manifest
    from ast2python.emission import emit_python_module
    from tests.test_target_qualifier_contracts import compile_body

    target = load_pinelib_target_manifest()
    compiled = compile_body("plot(math.abs(close))", target)
    calls = dict(target.call_bindings)
    key = next(
        key
        for key, row in calls.items()
        if row.symbol_id == "pine:function:math.abs" and 6 in row.supported_pine_versions
    )
    calls[key] = replace(calls[key], python_module=runtime_module)
    target = replace(target, call_bindings=MappingProxyType(calls))
    with pytest.raises(BundleInvariantError, match=code):
        emit_python_module(compiled.plan, target)


@pytest.mark.parametrize(
    "dtype,version,code",
    [
        ("array<int>", 4, "A2P_ARRAY_HISTORY_VERSION"),
        (None, 6, "A2P_HISTORY_TYPE"),
        ("unknown", 6, "A2P_HISTORY_TYPE"),
    ],
)
def test_history_requires_supported_version_and_concrete_stored_type(dtype, version, code):
    from ast2python.lowering.model import IRType

    graph = Graph()
    value = graph.literal(1)
    offset = graph.literal(0)
    root = graph.add("HistoryRefExpr", roles={"base": [value], "offset": [offset]})
    em = graph.emitter
    nodes = dict(em.plan.nodes)
    nodes[value] = replace(
        nodes[value], result_type=None if dtype is None else IRType(dtype, "series", False)
    )
    em.plan = replace(em.plan, pine_version=version, nodes=MappingProxyType(nodes))
    em.exact_pinelib = True
    with pytest.raises(BundleInvariantError, match=code):
        em._expr(root)


def test_global_capture_requires_an_admitted_series_slot():
    from ast2python import load_pinelib_target_manifest
    from ast2python.emission.python import _DirectEmitter
    from tests.test_historical_forward_execution import compile_source, source

    compiled = compile_source(source(6, "capture_edge=close\nf()=>capture_edge\nplot(f())"))
    em = _DirectEmitter(compiled.plan, load_pinelib_target_manifest())
    root = next(
        key
        for key in compiled.plan.ordered_ir_ids
        if em._attrs(key).get("ast_kind") == "Identifier"
        and em._fields(key).get("name") == "capture_edge"
    )
    em.current_function = "udf"
    local = em.lexical_names[em._attrs(root)["symbol_id"]][1]
    assert em._identifier(root).startswith("self.runtime.read_series(")
    # Corrupt only the admitted storage slot, keeping the lexical contract valid.
    del em.scalar_declarations[local]
    with pytest.raises(BundleInvariantError, match="A2P_UDF_GLOBAL_CAPTURE"):
        em._identifier(root)


def test_call_requires_version_bound_target_identity():
    em, root, _ = configured_call(Graph(), supported_pine_versions=(1,))
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_CALL_BINDING"):
        em._call(root)
