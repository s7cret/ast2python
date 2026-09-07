"""Typed maps/matrices and intrabar collection state in actual generated Pine."""

import hashlib
import json
from copy import deepcopy

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pinelib import CallbackFrame
from pinelib.errors import PineRuntimeError
from pinelib.runtime.metadata import BarValues
from pinelib.state.checkpoint import from_portable

from ast2python import BundleInvariantError, compile_consumer_bundle
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.lowering import load_pinelib_target_manifest
from tests.test_locked_library_execution import runtime_for
from tests.test_rc6_input_metadata import compile_source, run_source


def trace(body, version=6, closes=(1, 2, 3)):
    runtime, _, _ = run_source(
        f'//@version={version}\nindicator("collections")\n' + body + "\n", closes=closes
    )
    return [from_portable(e.payload["series"]) for e in runtime.visuals.committed]


PARTS = {
    "array": ("array.new<int>(1,0)", "array.set(a,0,array.get(a,0)+1)", "array.get(a,0)"),
    "matrix": (
        "matrix.new<int>(1,1,0)",
        "matrix.set(a,0,0,matrix.get(a,0,0)+1)",
        "matrix.get(a,0,0)",
    ),
    "map": (
        "map.new<string,int>()",
        'map.put(a,"n",(map.contains(a,"n") ? map.get(a,"n") : 0)+1)',
        'map.get(a,"n")',
    ),
}


def counter_body(kind, mode, local=False):
    constructor, update, read = PARTS[kind]
    body = f"{mode} a={constructor}\n{update}\n"
    return (
        ("f()=>\n    " + body.replace("\n", "\n    ") + read + "\nplot(f())")
        if local
        else body + "plot(" + read + ")"
    )


def tick(runtime, cls, sequence, bar, final):
    tx = runtime.begin(
        CallbackFrame("REALTIME_TICK", sequence, bar_index=bar, realtime=True, final_tick=final),
        values=BarValues(100, 101, 99, 100, 1, bar * 60000, (bar + 1) * 60000 - 1),
    )
    cls(tx).run()
    value = from_portable(runtime.visuals.working[-1].payload["series"])
    tx.commit()
    return value


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["array", "matrix", "map"])
@pytest.mark.parametrize("mode", ["var", "varip"])
@pytest.mark.parametrize("local", [False, True])
def test_real_ticks_keep_varip_contents_but_rollback_var(version, kind, mode, local):
    compiled = compile_source(
        f'//@version={version}\nindicator("ticks")\n' + counter_body(kind, mode, local) + "\n"
    )
    runtime, cls = runtime_for(compiled)
    actual = [tick(runtime, cls, i, 0, i == 3) for i in range(4)]
    assert actual == ([1, 2, 3, 4] if mode == "varip" else [1, 1, 1, 1])
    # New bar begins from the previous committed value in either mode.
    assert tick(runtime, cls, 4, 1, True) == (5 if mode == "varip" else 2)


@pytest.mark.parametrize("kind", ["array", "matrix", "map"])
def test_generated_varip_checkpoint_continuation_equals_uninterrupted(kind):
    compiled = compile_source(
        '//@version=6\nindicator("checkpoint")\n' + counter_body(kind, "varip", True) + "\n"
    )
    a, cls = runtime_for(compiled)
    assert tick(a, cls, 0, 0, False) == 1
    assert tick(a, cls, 1, 0, True) == 2
    b, _ = runtime_for(compiled)
    b.restore(json.loads(json.dumps(a.checkpoint().to_dict())))
    for runtime in (a, b):
        assert [tick(runtime, cls, i, 1, i == 4) for i in (2, 3, 4)] == [3, 4, 5]
    assert a.checkpoint().to_dict() == b.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("indexed", [False, True])
def test_matrix_rows_and_nested_array_iteration_have_typed_values(version, indexed):
    target = "[i,row]" if indexed else "row"
    body = f"m=matrix.new<int>(2,2,1)\nmatrix.set(m,1,1,4)\ns=0\nfor {target} in m\n    for v in row\n        s+=v\nplot(s)"
    assert trace(body, version) == [7] * 3


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("control", ["plain", "break", "continue"])
def test_map_loop_values_preserve_insertion_order_and_control(version, control):
    setup = 'm=map.new<string,int>()\nmap.put(m,"first",1)\nmap.put(m,"second",2)\nmap.put(m,"third",3)\n'
    clause = "" if control == "plain" else f'    if k=="third"\n        {control}\n'
    body = setup + "x=for [k,v] in m\n" + clause + "    v*10\nplot(x)"
    assert trace(body, version) == [30 if control == "plain" else 20] * 3


def test_map_values_are_live_and_guard_is_released_after_break():
    body = 'm=map.new<string,int>()\nmap.put(m,"a",1)\nmap.put(m,"b",2)\ns=0\nfor [k,v] in m\n    if k=="a"\n        map.put(m,"b",7)\n    s+=v\nfor [k,v] in m\n    break\nmap.put(m,"c",9)\nplot(s)\nplot(map.size(m))'
    assert trace(body, closes=[1]) == [8, 3]


@pytest.mark.parametrize("mutation", ['map.put(m,"c",3)', 'map.remove(m,"b")', "map.clear(m)"])
def test_map_structure_change_fails_before_mutation_and_abort_is_exact(mutation):
    body = (
        'm=map.new<string,int>()\nmap.put(m,"a",1)\nmap.put(m,"b",2)\nfor [k,v] in m\n    '
        + mutation
        + "\n    break\n"
    )
    compiled = compile_source('//@version=6\nindicator("mutation")\n' + body)
    runtime, cls = runtime_for(compiled)
    before = runtime.checkpoint().to_dict()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    with pytest.raises(PineRuntimeError, match="keys cannot change"):
        cls(tx).run()
    assert not runtime.references._map_iterations
    tx.abort()
    assert before == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("kind", ["keys", "values"])
def test_map_projection_is_a_pine_array_with_copy_semantics(kind):
    body = 'm=map.new<string,int>()\nmap.put(m,"b",2)\nmap.put(m,"a",1)\na=map.' + kind + "(m)\n"
    if kind == "keys":
        body += 'array.set(a,0,"other")\nplot(map.get(m,"b"))\n'
    else:
        body += 'array.set(a,0,9)\nplot(map.get(m,"b"))\n'
    assert trace(body) == [2] * 3


@pytest.mark.parametrize(
    "expression,read,expected",
    [
        ("array.new<int>()", "array.size(a)", 0),
        ("matrix.new<float>()", "matrix.rows(a)+matrix.columns(a)", 0),
        ("matrix.new<float>(1,2)", "na(matrix.get(a,0,1)) ? 1 : 0", 1),
        ("map.new<string,int>()", "map.size(a)", 0),
    ],
)
def test_generic_defaults_and_runtime_shape(expression, read, expected):
    assert trace("a=" + expression + "\nplot(" + read + ")") == [expected] * 3


@pytest.mark.parametrize(
    "field,body",
    [
        ("compiled_varip_reference_storage", counter_body("array", "varip")),
        ("compiled_collection_iteration", "m=map.new<string,int>()\nfor [k,v] in m\n    x=v"),
    ],
)
def test_new_compilation_requires_explicit_matching_runtime_contract(tmp_path, field, body):
    from pinelib.abi import load_target_manifest

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
    source = '//@version=6\nindicator("old")\n' + body + "\n"
    with pytest.raises(BundleInvariantError, match="language contract"):
        compile_consumer_bundle(build_consumer_bundle(source), target=target)


@pytest.mark.parametrize("kind", ["array", "map", "matrix"])
def test_two_written_varip_udf_calls_remain_independent_across_ticks(kind):
    constructor, update, read = PARTS[kind]
    update = update.replace("+1", "+step")
    source = (
        '//@version=6\nindicator("calls")\nf(int step)=>\n    varip a='
        + constructor
        + "\n    "
        + update
        + "\n    "
        + read
        + "\nx=f(1)\ny=f(10)\nplot(x+y)\n"
    )
    runtime, cls = runtime_for(compile_source(source))
    assert [tick(runtime, cls, i, 0, i == 2) for i in range(3)] == [11, 22, 33]


def test_reassigned_varip_reference_and_array_history_keep_distinct_instances():
    body = (
        "varip a=array.new<int>(1,0)\na:=array.new<int>(1,array.get(a,0)+1)\nplot(array.get(a,0))"
    )
    runtime, cls = runtime_for(compile_source('//@version=6\nindicator("new")\n' + body + "\n"))
    assert [tick(runtime, cls, i, 0, i == 2) for i in range(3)] == [1, 2, 3]
    assert len(runtime.references.to_json()["objects"]) == 4


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["map", "matrix"])
def test_locked_collection_export_executes_and_preserves_intrabar_state(version, kind):
    from tests.test_locked_library_execution import compile_linked, library, script

    decl, update, get = PARTS[kind]
    body = f"export f()=>\n    varip a={decl}\n    {update}\n    s=0\n"
    if kind == "map":
        body += "    for [k,v] in a\n        s+=v\n    s"
    else:
        body += "    for row in a\n        s+=array.get(row,0)\n    s"
    compiled, linked = compile_linked(
        script("plot(lib.f())", version=version), {"user/Lib/1": library(body, version=version)}
    )
    assert linked.receipt()["profile"] == "same_version_collections_v3"
    runtime, cls = runtime_for(compiled)
    assert [tick(runtime, cls, i, bar=0, final=(i == 3)) for i in range(4)] == [1, 2, 3, 4]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["map", "matrix"])
def test_locked_typed_collection_parameter_executes_same_as_direct(version, kind):
    from tests.test_locked_library_execution import advance, compile_linked, library, script

    if kind == "map":
        body = 'export f(map<string,int> m)=>\n    map.put(m,"a",2)\n    s=0\n    for [k,v] in m\n        s+=v\n    s'
        setup = "m=map.new<string,int>()"
        expected = 2
    else:
        body = "export f(matrix<int> m)=>\n    s=0\n    for row in m\n        s+=array.get(row,0)\n    s"
        setup = "m=matrix.new<int>(2,1,3)"
        expected = 6
    compiled, linked = compile_linked(
        script(setup + "\nplot(lib.f(m))", version=version),
        {"user/Lib/1": library(body, version=version)},
    )
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1, 2, 3]) == [expected] * 3
    assert linked.receipt()["profile"] == "same_version_collections_v3"
