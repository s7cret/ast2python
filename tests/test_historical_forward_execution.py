"""Historical forward references are evaluated, not patched with missing-value defaults.

The v3 migration explicitly removes v2 forward references:
https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-3/
The committed v2-forward-bool corpus supplies the original fuzz regression.
"""

from pathlib import Path

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError
from pinelib.state.checkpoint import from_portable

from ast2python import compile_reference_consumer_bundle, load_reference_target_manifest
from ast2python.hardening.fuzz import _ReferenceRuntime
from tests.test_rc6_input_metadata import compile_source, run_source


def source(version, body):
    declaration = "study" if version < 5 else "indicator"
    return f'//@version={version}\n{declaration}("forward dependencies")\n{body}\n'


def plotted(runtime):
    return [from_portable(event.payload["series"]) for event in runtime.visuals.committed]


def test_committed_v2_forward_bool_fuzz_case_executes_without_changing_its_input():
    path = Path(__file__).parent / "corpus/v2/v2-forward-bool.bundle.json"
    result = compile_reference_consumer_bundle(path)
    namespace = {}
    exec(compile(result.emitted.code, "forward_fuzz.py", "exec"), namespace)
    namespace["GeneratedScript"](_ReferenceRuntime(load_reference_target_manifest())).run()


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize(
    "body,expected",
    [
        ("a=b\nb=7\nplot(a)", [7]),
        ("a=b\nb=c\nc=7\nplot(a)\nplot(b)", [7, 7]),
        ("plot(b)\nb=7", [7]),
        ("a=b+true\nb=1\nplot(a)", [2]),
        ("plot(3)\na=b\nb=7\nplot(a)\nplot(9)", [3, 7, 9]),
    ],
)
def test_historical_dependencies_initialize_once_before_their_current_bar_reads(
    version, body, expected
):
    runtime, _, _ = run_source(source(version, body), closes=[1])
    assert plotted(runtime) == expected


def test_forward_dependency_is_not_reinitialized_after_a_later_reassignment():
    runtime, _, _ = run_source(source(2, "a=b\nb=7\nb:=9\nplot(a)\nplot(b)"), closes=[1])
    assert plotted(runtime) == [7, 9]


@pytest.mark.parametrize("version", [1, 2])
def test_forward_series_values_are_recomputed_for_each_bar(version):
    runtime, _, _ = run_source(source(version, "a=b\nb=close\nplot(a)"), closes=[7, 9])
    assert plotted(runtime) == [7, 9]


@pytest.mark.parametrize("version", [3, 4, 5, 6])
def test_newer_versions_still_reject_forward_reference_at_the_producer(version):
    with pytest.raises(ConsumerBundleError, match="production-blocking diagnostics"):
        compile_source(source(version, "a=b\nb=7\nplot(a)"))


@pytest.mark.parametrize("version", range(1, 7))
def test_already_ordered_declarations_preserve_independent_statement_order(version):
    runtime, _, _ = run_source(source(version, "b=7\nplot(3)\na=b\nplot(a)"), closes=[1])
    assert plotted(runtime) == [3, 7]


def test_historical_delayed_dependency_is_not_a_current_bar_cycle():
    # Explicit first-bar bootstrap isolates ordering from the absent nz target binding.
    runtime, _, _ = run_source(
        source(2, "d=f[1]\ne=time==0?1:d+1\nf=e+close\nplot(f)"), closes=[1, 1]
    )
    assert plotted(runtime) == [2, 4]


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize(
    "expression,expected",
    [
        ("true+1", 2),
        ("false+1", 1),
        ("true+false", 1),
        ("1.5+true", 2.5),
    ],
)
def test_admitted_historical_bool_coercions_reach_the_strict_numeric_abi(
    version, expression, expected
):
    runtime, _, _ = run_source(source(version, f"plot({expression})"), closes=[1])
    assert plotted(runtime) == [expected]


@pytest.mark.parametrize("version", [1, 2])
def test_historical_bool_coercion_preserves_na(version):
    from pinelib import is_na

    runtime, _, _ = run_source(source(version, "b=close>0?true:na\nplot(b+1)"), closes=[1, 0])
    actual = plotted(runtime)
    assert actual[0] == 2
    assert is_na(actual[1])


@pytest.mark.parametrize("version", [3, 4, 5, 6])
def test_modern_versions_do_not_gain_bool_to_number_coercion(version):
    with pytest.raises(ConsumerBundleError, match="production-blocking diagnostics"):
        compile_source(source(version, "plot(true+1)"))


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("offset", ["0", "lag"])
def test_zero_and_dynamic_history_offsets_keep_current_bar_dependencies(version, offset):
    runtime, _, _ = run_source(source(version, f"a=b[{offset}]\nlag=0\nb=7\nplot(a)"), closes=[1])
    assert plotted(runtime) == [7]


def test_post_admission_current_bar_cycle_fails_closed():
    from dataclasses import replace
    from types import MappingProxyType

    from ast2python.admission.canonical import freeze_json
    from ast2python.emission.ordering import ordered_global_items
    from ast2python.emission.python import _DirectEmitter
    from ast2python.errors import BundleInvariantError

    compiled = compile_source(source(2, "a=1\nb=a\nplot(b)"))
    from ast2python import load_pinelib_target_manifest

    em = _DirectEmitter(compiled.plan, load_pinelib_target_manifest())
    items = em._role(em.plan.root_ir_id, "items")
    first = em._role(items[0], "initializer")[0]
    second = em._role(items[1], "initializer")[0]
    attrs = em._attrs(second)
    attrs["fields"]["name"] = "b"
    attrs["symbol_id"] = em._attrs(items[1])["symbol_id"]
    nodes = dict(em.plan.nodes)
    nodes[first] = replace(
        nodes[second], ir_id=first, source=nodes[first].source, attributes=freeze_json(attrs)
    )
    em.plan = replace(em.plan, nodes=MappingProxyType(nodes))
    with pytest.raises(BundleInvariantError, match="A2P_FORWARD_REFERENCE_CYCLE"):
        ordered_global_items(em, items)


@pytest.mark.parametrize("version", [1, 2])
def test_explicit_producer_identity_controls_historical_name_collision(version):
    # Preserve transport evidence, but never turn an unproven historic policy into execution.
    from pine2ast.hardening.consumer_bundle import build_consumer_bundle

    from ast2python.errors import BundleInvariantError

    code = source(version, "plot(n)\nn=7\nplot(n)")
    bundle = build_consumer_bundle(code, producer_commit="1" * 40)
    facts = bundle["semantic_facts"]["facts"]
    declaration = next(
        row for row in facts if row["kind"] == "VarDeclaration" and row["declaration_target"] == "n"
    )
    references = [
        row
        for row in facts
        if row["kind"] == "Identifier"
        and row["span"]["start_line"] in {3, 5}
        and row["span"]["start_col"] == 6
    ]
    assert len(references) == 2
    assert all(row["symbol_id"] == declaration["symbol_id"] for row in references)
    with pytest.raises(BundleInvariantError, match="A2P_HISTORICAL_BINDING_AMBIGUOUS"):
        compile_source(code)


@pytest.mark.parametrize("version", [1, 2])
def test_unambiguous_declared_local_reads_use_the_same_generated_storage(version):
    import ast

    compiled = compile_source(source(version, "n=7\nplot(n)\nplot(n)"))
    run = next(
        node
        for node in ast.walk(ast.parse(compiled.emitted.code))
        if isinstance(node, ast.FunctionDef) and node.name == "run"
    )
    assignments = [node for node in run.body if isinstance(node, ast.Assign)]
    assert len(assignments) == 1
    target = assignments[0].targets[0]
    assert isinstance(target, ast.Name)
    series = [
        kw.value
        for node in ast.walk(run)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "series"
    ]
    assert len(series) == 2
    assert all(isinstance(value, ast.Name) and value.id == target.id for value in series)
