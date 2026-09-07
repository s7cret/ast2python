"""Independent reference identities and exact loop-result control flow."""

import pytest
from pinelib import is_na
from pinelib.state.checkpoint import from_portable

from tests.test_rc6_input_metadata import compile_source, run_source


def trace(body, version=6, closes=(1, 2, 3)):
    declaration = "indicator" if version >= 5 else "study"
    runtime, _, _ = run_source(
        f'//@version={version}\n{declaration}("refs/loops")\n' + body + "\n", closes=closes
    )
    return [from_portable(row.payload["series"]) for row in runtime.visuals.committed]


@pytest.mark.parametrize("version", [4, 5, 6])
@pytest.mark.parametrize("explicit", [False, True])
def test_persistent_array_in_udf_keeps_contents_without_reallocating(version, explicit):
    annotation = ("float[] " if version == 4 else "array<float> ") if explicit else ""
    body = f"f() =>\n    var {annotation}a=array.new_float()\n    array.push(a,close)\n    array.size(a)\nplot(f())"
    assert trace(body, version) == [1, 2, 3]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("mode", ["identifier", "call", "udf_local"])
def test_history_is_previous_array_instance_not_current_payload(version, mode):
    if mode == "identifier":
        body = "a=array.new_float(1,close)\nb=a[1]\n"
    elif mode == "call":
        body = "f() =>\n    array.new_float(1,close)\nb=f()[1]\n"
    else:
        body = "f() =>\n    a=array.new_float(1,close)\n    b=a[1]\n    na(b) ? 0 : array.get(b,0)\nplot(f())"
        assert trace(body, version) == [0, 1, 2]
        return
    assert trace(body + "plot(na(b) ? 0 : array.get(b,0))", version) == [0, 1, 2]


def test_reference_history_v4_is_not_silently_admitted():
    with pytest.raises(ValueError, match="production-blocking diagnostics"):
        compile_source('//@version=4\nstudy("negative")\na=array.new_float(1,close)\nb=a[1]\n')


def test_one_constructor_in_loop_allocates_distinct_instances_and_lazily_retained_vars():
    body = "var a=array.new_float()\nfor i=1 to 3\n    b=array.new_float(1,i)\n    array.push(a,array.get(b,0))\nplot(array.size(a))"
    assert trace(body) == [3, 6, 9]


def test_udf_reference_parameter_mutates_shared_array_but_written_calls_keep_private_var():
    body = "f(array<float> a, int step) =>\n    var p=array.new_float()\n    array.push(p,step)\n    array.push(a,step)\n    array.size(p)\nvar a=array.new_float()\nx=f(a,1)\ny=f(a,10)\nplot(x+y)\nplot(array.size(a))"
    assert trace(body) == [2, 2, 4, 4, 6, 6]


def test_alias_assignment_is_reference_identity_not_a_deep_copy():
    assert trace(
        "a=array.new_float(1,close)\nb=a\narray.set(b,0,close+10)\nplot(array.get(a,0))"
    ) == [11, 12, 13]


def test_persistent_array_history_keeps_same_object_not_frozen_payload():
    body = (
        "var a=array.new_float(1,0)\narray.set(a,0,close)\nb=a[1]\nplot(na(b) ? 0 : array.get(b,0))"
    )
    assert trace(body) == [0, 2, 3]


def test_reference_returned_from_conditional_or_loop_is_bound():
    body = "a=for i=1 to 3\n    array.new_float(1,i+close)\nb=if close>1\n    a\nelse\n    array.new_float(1,0)\nplot(array.get(b,0))"
    assert trace(body) == [0, 5, 6]


RANGE_CASES = [
    ("x=for i=1 to 4\n    i*2\nplot(x)", 8),
    ("x=for i=4 to 1\n    i*2\nplot(x)", 2),
    ("x=for i=1 to 6 by 2\n    i*2\nplot(x)", 10),
    ("x=for i=1 to 4\n    if i==3\n        break\n    i*2\nplot(x)", 4),
    ("x=for i=1 to 4\n    if i==4\n        continue\n    i*2\nplot(x)", 6),
    ("x=for i=1 to 4\n    if i==3\n        break\n    else\n        i*2\nplot(x)", 4),
    ("x=for i=1 to 4\n    if i==4\n        continue\n    else\n        i*2\nplot(x)", 6),
    ("x=for i=1 to 2\n    for j=1 to 3\n        i+j\nplot(x)", 5),
    ("f() =>\n    for i=1 to 3\n        i*2\nplot(f())", 6),
    ("i=99\nx=for i=1 to 3\n    i*2\nplot(x+i)", 105),
]


@pytest.mark.parametrize("version", [3, 4, 5, 6])
@pytest.mark.parametrize("body,expected", RANGE_CASES)
def test_loop_value_is_last_completed_iteration_with_lexical_control(version, body, expected):
    assert trace(body, version) == [expected] * 3


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["plain", "break", "continue", "empty"])
def test_while_return_values_and_outer_mutation(version, kind):
    ending = {
        "plain": "    i*2",
        "break": "    if i==3\n        break\n    i*2",
        "continue": "    if i==3\n        continue\n    i*2",
        "empty": "    i*2",
    }[kind]
    body = (
        "i=0\nx=while "
        + ("false" if kind == "empty" else "i<3")
        + "\n    i+=1\n"
        + ending
        + "\nplot(x)\nplot(i)"
    )
    result = trace(body, version)
    for j in range(0, len(result), 2):
        if kind == "empty":
            assert is_na(result[j]) and result[j + 1] == 0
        else:
            assert result[j : j + 2] == [6 if kind == "plain" else 4, 3]


@pytest.mark.parametrize("indexed", [False, True])
def test_for_in_keeps_index_and_value_and_returns_last_completed_value(indexed):
    target = "[i,v]" if indexed else "v"
    value = "i+v" if indexed else "v*2"
    assert trace(
        "a=array.new_float(3,close)\nx=for " + target + " in a\n    " + value + "\nplot(x)"
    ) == ([3, 4, 5] if indexed else [2, 4, 6])


@pytest.mark.parametrize("kind", ["empty", "all_continue", "first_break"])
def test_tuple_no_value_preserves_arity_and_missing_elements(kind):
    if kind == "empty":
        body = "[a,b]=while false\n    [1,2]"
    else:
        body = (
            "[a,b]=for i=1 to 3\n    "
            + ("continue" if kind == "all_continue" else "break")
            + "\n    [i,i+1]"
        )
    assert trace(body + "\nplot(na(a) and na(b))") == [True] * 3


def test_tuple_from_loop_or_udf():
    assert trace("[a,b]=for i=1 to 3\n    [i,i+1]\nplot(a+b)") == [7] * 3
    assert trace("f() =>\n    for i=1 to 3\n        [i,i+1]\n[a,b]=f()\nplot(a+b)") == [7] * 3


@pytest.mark.parametrize("mode", ["default", "var"])
def test_loop_initializer_of_persistent_binding_runs_only_when_needed(mode):
    qualifier = "" if mode == "default" else "var "
    body = "var int n=0\n" + qualifier + "x=for i=1 to 2\n    n+=1\n    n\nplot(x)\nplot(n)"
    assert trace(body) == ([2, 2, 4, 4, 6, 6] if mode == "default" else [2, 2] * 3)


@pytest.mark.parametrize(
    "statement",
    [
        "i=0\nx=while close>0\n    i+=1\n    i",
        "a=array.new_float(1,0)\nx=for v in a\n    array.push(a,v)\n    v",
        "x=for i=1 to 3\n    for j=1 to 3\n        j",
    ],
)
def test_every_loop_form_consumes_shared_callback_budget_and_abort_remains_exact(statement):
    from dataclasses import replace

    from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession
    from pinelib.errors import PineRuntimeError
    from pinelib.runtime.metadata import BarValues
    from pinelib.runtime.policies import ResourcePolicy, RuntimePolicies

    result = compile_source('//@version=6\nindicator("budget")\n' + statement + "\nplot(x)\n")
    module = {}
    exec(result.emitted.code, module)
    runtime = RuntimeSession(
        RuntimeLanguageContext(6, "test", "pine-v6", "sha256:" + "a" * 64, "compiler_annotation"),
        RuntimePolicies(resource=replace(ResourcePolicy(), max_loop_iterations=5)),
    )
    before = runtime.checkpoint().to_dict()
    tx = runtime.begin(
        CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0), values=BarValues(1, 2, 0, 1, 0, 0, 59999)
    )
    with pytest.raises(PineRuntimeError, match="budget"):
        module["GeneratedScript"](tx).run()
    tx.abort()
    assert runtime.checkpoint().to_dict() == before


@pytest.mark.parametrize(
    "field,body",
    [
        ("compiled_reference_storage", "a=array.new_float(1,1)\nplot(array.get(a,0))"),
        ("compiled_loop_values", "x=for i=1 to 3\n    i\nplot(x)"),
    ],
)
def test_older_or_incomplete_exact_target_cannot_admit_new_language_calls(tmp_path, field, body):
    import hashlib
    import json
    from copy import deepcopy

    from pine2ast.hardening.consumer_bundle import build_consumer_bundle
    from pinelib.abi import load_target_manifest

    from ast2python import BundleInvariantError, compile_consumer_bundle
    from ast2python.admission.canonical import canonical_json_bytes
    from ast2python.lowering import load_pinelib_target_manifest

    raw = deepcopy(load_target_manifest())
    raw.pop(field)
    raw["content_hash"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes({k: v for k, v in raw.items() if k != "content_hash"})
        ).hexdigest()
    )
    path = tmp_path / "target.json"
    path.write_text(json.dumps(raw))
    target = load_pinelib_target_manifest(path)
    bundle = build_consumer_bundle('//@version=6\nindicator("old target")\n' + body + "\n")
    with pytest.raises(BundleInvariantError, match="language contract"):
        compile_consumer_bundle(bundle, target=target)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["parameter", "persistent", "return", "for_in"])
def test_locked_library_references_and_loops_use_the_same_runtime_and_resume(version, kind):
    import json

    from tests.test_locked_library_execution import (
        advance,
        compile_linked,
        library,
        runtime_for,
        script,
    )

    bodies = {
        "parameter": (
            "export f(array<float> a, float x) =>\n    array.push(a,x)\n    array.size(a)",
            "var a=array.new_float()\nplot(lib.f(a,close))",
            [1, 2, 3],
        ),
        "persistent": (
            "export f(float x) =>\n    var a=array.new_float()\n    array.push(a,x)\n    array.size(a)",
            "plot(lib.f(close))",
            [1, 2, 3],
        ),
        "return": (
            "export f(float x) =>\n    for i=1 to 3\n        array.new_float(1,x+i)",
            "a=lib.f(close)\nplot(array.get(a,0))",
            [4, 5, 6],
        ),
        "for_in": (
            "export f(array<float> a) =>\n    total=0.0\n    for v in a\n        total+=v\n    total",
            "a=array.new_float(3,close)\nplot(lib.f(a))",
            [3, 6, 9],
        ),
    }
    body, main, expected = bodies[kind]
    result, linked = compile_linked(
        script(main, version=version), {"user/Lib/1": library(body, version=version)}
    )
    assert linked.receipt()["profile"] == "same_version_arrays_v2"
    whole, cls = runtime_for(result)
    assert advance(whole, cls, [1, 2, 3]) == expected
    part, _ = runtime_for(result)
    advance(part, cls, [1])
    resumed, _ = runtime_for(result)
    resumed.restore(json.loads(json.dumps(part.checkpoint().to_dict())))
    advance(resumed, cls, [2, 3], start=1)
    assert resumed.checkpoint().to_dict() == whole.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["if", "switch"])
@pytest.mark.parametrize("dtype", ["int", "bool"])
def test_last_iteration_with_no_matching_branch_returns_missing_not_prior_iteration(
    version, kind, dtype
):
    value = "5" if dtype == "int" else "true"
    branch = (
        f"    if i==1\n        {value}" if kind == "if" else f"    switch i\n        1 => {value}"
    )
    body = "x=for i=1 to 3\n" + branch + "\n"
    if dtype == "bool" and version == 6:
        assert trace(body + "plot(x)", version) == [False] * 3
    else:
        assert trace(body + "plot(na(x))", version) == [True] * 3
