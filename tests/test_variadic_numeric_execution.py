"""All variadic operands cross the producer/compiler/runtime boundary in order."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pinelib import CallbackFrame
from pinelib.runtime.metadata import BarValues
from pinelib.state.checkpoint import from_portable

from ast2python.admission.ast_view import StrictASTView
from ast2python.admission.facts import SemanticFactsIndex
from ast2python.errors import BundleInvariantError
from ast2python.lowering import audit_pinelib_call_binding, load_pinelib_target_manifest
from tests.test_locked_library_execution import runtime_for
from tests.test_rc6_input_metadata import compile_source, run_source

# Independent literal ordering, authored before compiler/target changes.
CASES = [
    ("2,1", 1, 2),
    ("2,1,3", 1, 3),
    ("-4,-2,-9", -9, -2),
    ("5,5,5", 5, 5),
    ("0,-1,1,0", -1, 1),
    ("1.25,-2.5,0.5", -2.5, 1.25),
    ("2,1.5,3", 1.5, 3),
    ("9,8,7,6,5", 5, 9),
]


def source(body, version):
    return f'//@version={version}\nindicator("variadic")\n{body}\n'


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name,index", [("min", 1), ("max", 2)])
@pytest.mark.parametrize("case", CASES)
def test_every_numeric_operand_reaches_existing_runtime_kernel(version, name, index, case):
    runtime, _, _ = run_source(source(f"plot(math.{name}({case[0]}))", version), closes=[1])
    actual = [from_portable(e.payload["series"]) for e in runtime.visuals.committed]
    assert actual == [case[index]]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("path", ["historical", "realtime", "abort_retry", "checkpoint"])
def test_variadic_nested_series_operands_survive_callback_boundaries(version, path):
    compiled = compile_source(
        source("f(float x)=>math.min(x,2,math.max(-1,x-1,0))\nplot(f(close))", version)
    )
    runtime, cls = runtime_for(compiled)
    actual = []
    sequence = 0
    for bar, close in enumerate([-2, 1, 4]):

        def execute(sequence, trial=False, runtime=runtime, cls=cls, bar=bar, close=close):
            tx = runtime.begin(
                CallbackFrame(
                    "REALTIME_TICK" if path in {"realtime", "abort_retry"} else "HISTORICAL_EVAL",
                    sequence,
                    bar_index=bar,
                    realtime=path in {"realtime", "abort_retry"},
                    final_tick=not trial,
                ),
                values=BarValues(
                    close, close + 1, close - 1, close, 1, bar * 60000, bar * 60000 + 59999
                ),
            )
            cls(tx).run()
            value = from_portable(runtime.visuals.working[-1].payload["series"])
            if trial and path == "abort_retry":
                tx.abort()
            else:
                tx.commit()
            return value

        if path in {"realtime", "abort_retry"}:
            execute(sequence, True)
            if path == "realtime":
                sequence += 1
        actual.append(execute(sequence))
        sequence += 1
        if path == "checkpoint" and bar == 0:
            checkpoint = json.loads(json.dumps(runtime.checkpoint().to_dict()))
            runtime, cls = runtime_for(compiled)
            runtime.restore(checkpoint)
    assert actual == [-2, 0, 2]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name", ["min", "max"])
def test_operand_evaluation_occurs_once_in_source_order(version, name):
    body = (
        "var a=array.new_int(0)\n"
        "record(int n)=>\n    array.push(a,n)\n    n\n"
        f"plot(math.{name}(record(2),record(1),record(3)))\n"
        "plot(array.size(a))\nplot(array.get(a,0))\n"
        "plot(array.get(a,1))\nplot(array.get(a,2))"
    )
    runtime, _, _ = run_source(source(body, version), closes=[1])
    assert [from_portable(e.payload["series"]) for e in runtime.visuals.committed] == [
        1 if name == "min" else 3,
        3,
        2,
        1,
        3,
    ]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "mutation", ["order", "index", "name", "expected_type", "qualifier", "binding"]
)
def test_variadic_admission_rejects_changed_group_identity(version, mutation):
    bundle = build_consumer_bundle(source("plot(math.min(2,1,3))", version))
    payload = deepcopy(bundle["semantic_facts"])
    call = next(row for row in payload["calls"] if row["callee"] == "math.min")
    if mutation == "order":
        call["arguments"].reverse()
    else:
        field, value = {
            "index": ("parameter_index", 1),
            "name": ("parameter_name", "wrong"),
            "expected_type": ("expected_type", "any"),
            "qualifier": ("max_qualifier", "const"),
            "binding": ("binding", "positional"),
        }[mutation]
        call["arguments"][1][field] = value
    ast = StrictASTView.build(
        bundle["ast"], bundle["node_index"], version_context=bundle["version_context"]
    )
    with pytest.raises(BundleInvariantError):
        SemanticFactsIndex.build(
            payload, ast_view=ast, version_context=bundle["version_context"], production=True
        )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name", ["min", "max"])
def test_exact_variadic_abi_mapping_is_audited(version, name):
    symbol = "pine:function:math." + name
    binding = load_pinelib_target_manifest().call_bindings[
        (symbol, symbol + "#canonical", "NAMESPACE_FUNCTION")
    ]
    assert not audit_pinelib_call_binding(
        binding, [{"name": "values", "variadic": True}], pine_version=version
    )
    stale = replace(
        binding,
        parameter_bindings=(
            {"abi_parameter": "values", "binding": "SOURCE_PARAMETER", "source": "values"},
        ),
    )
    assert audit_pinelib_call_binding(
        stale, [{"name": "values", "variadic": True}], pine_version=version
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("source_name", ["wrong", None, ["values"]])
def test_variadic_spread_cannot_bind_unknown_or_malformed_source(version, source_name):
    symbol = "pine:function:math.min"
    original = load_pinelib_target_manifest().call_bindings[
        (symbol, symbol + "#canonical", "NAMESPACE_FUNCTION")
    ]
    forged = replace(
        original,
        parameter_bindings=(
            {"abi_parameter": "values", "binding": "SOURCE_VARIADIC", "source": source_name},
        ),
    )
    assert audit_pinelib_call_binding(
        forged, [{"name": "values", "variadic": True}], pine_version=version
    )


@pytest.mark.parametrize("version", [5, 6])
def test_variadic_label_does_not_admit_duplicate_scalar_parameters(version):
    bundle = build_consumer_bundle(source("plot(math.pow(2,3))", version))
    payload = deepcopy(bundle["semantic_facts"])
    call = next(row for row in payload["calls"] if row["callee"] == "math.pow")
    for row in call["arguments"]:
        row.update(binding="vararg", parameter_index=0, parameter_name="base")
    ast = StrictASTView.build(
        bundle["ast"], bundle["node_index"], version_context=bundle["version_context"]
    )
    with pytest.raises(BundleInvariantError, match="A2P_CALL_VARIADIC_CONTRACT"):
        SemanticFactsIndex.build(
            payload, ast_view=ast, version_context=bundle["version_context"], production=True
        )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("value", [None, [], True])
def test_malformed_variadic_identity_fails_as_admission_error(version, value):
    bundle = build_consumer_bundle(source("plot(math.min(2,1))", version))
    payload = deepcopy(bundle["semantic_facts"])
    call = next(row for row in payload["calls"] if row["callee"] == "math.min")
    call["arguments"][1]["parameter_index"] = value
    ast = StrictASTView.build(
        bundle["ast"], bundle["node_index"], version_context=bundle["version_context"]
    )
    with pytest.raises(BundleInvariantError, match="A2P_CALL_VARIADIC_CONTRACT"):
        SemanticFactsIndex.build(
            payload, ast_view=ast, version_context=bundle["version_context"], production=True
        )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("value", [0, 1, 0.0, 1.0])
def test_source_variadic_flag_requires_exact_boolean(version, value):
    symbol = "pine:function:math.exp"
    binding = load_pinelib_target_manifest().call_bindings[
        (symbol, symbol + "#canonical", "NAMESPACE_FUNCTION")
    ]
    assert audit_pinelib_call_binding(
        binding, [{"name": "number", "variadic": value}], pine_version=version
    ) == ("A2P_PINELIB_SOURCE_SIGNATURE_UNVERIFIED",)
