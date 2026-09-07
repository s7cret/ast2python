"""Typed collection variables and call boundaries through checked generated Pine.

Expected values are hand-derived; these are not external TV execution fixtures.
"""

import json

import pytest
from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, is_na
from pinelib.runtime.metadata import BarValues
from pinelib.state.checkpoint import from_portable

from tests.test_rc6_input_metadata import compile_source, run_source
from tests.test_stage2_language_execution import source, traces


@pytest.mark.parametrize("version", [4, 5, 6])
@pytest.mark.parametrize("mode", ["", "var ", "varip "])
def test_typed_arrays_persist_or_allocate_fresh_by_declaration(mode, version):
    out = traces(
        mode
        + ("float[] " if version == 4 else "array<float> ")
        + "a=array.new_float(1,0)\narray.set(a,0,array.get(a,0)+1)\nplot(array.get(a,0))",
        version=version,
    )
    assert out == ([1, 2, 3, 4] if mode else [1, 1, 1, 1])


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("float", "close", [1, 2, 3, 4]),
        ("int", "7", [7] * 4),
        ("bool", "close>2", [False, False, True, True]),
    ],
)
def test_generic_array_constructor_uses_checked_concrete_type(kind, value, expected, version):
    assert (
        traces(f"a=array.new<{kind}>(1,{value})\nplot(array.get(a,0))", version=version) == expected
    )


@pytest.mark.parametrize("kind", ["float", "int", "bool", "string", "color"])
def test_generic_primitive_descriptor_matches_runtime(kind):
    values = {"float": "1.5", "int": "1", "bool": "false", "string": '"x"', "color": "#ff0000"}
    r, _, _ = run_source(
        source(f"a=array.new<{kind}>(1,{values[kind]})\nplot(array.size(a))"), closes=[1]
    )
    assert len(r.references.to_json()["objects"]) == 1
    assert r.references.to_json()["objects"][0]["type_descriptor"] == kind


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["map", "matrix"])
def test_generic_map_matrix_variables_arguments_and_global_capture(kind, version):
    if kind == "map":
        body = 'var m=map.new<string,float>()\nread(map<string,float> a)=>map.get(a,"x")\nwrite()=>map.put(m,"x",close)\nwrite()\nplot(read(m))'
    else:
        body = "var m=matrix.new<float>(1,1,0)\nread(matrix<float> a)=>matrix.get(a,0,0)\nwrite()=>matrix.set(m,0,0,close)\nwrite()\nplot(read(m))"
    assert traces(body, version=version) == [1, 2, 3, 4]


@pytest.mark.parametrize("named", [False, True])
def test_function_mutation_keeps_alias_and_reference_returns(named):
    args = "a=a, value=close" if named else "a,close"
    body = (
        "set(array<float> a,float value)=>\n    array.set(a,0,value)\n    a\na=array.new_float(1,0)\nb=set("
        + args
        + ")\narray.set(b,0,array.get(b,0)+1)\nplot(array.get(a,0))"
    )
    assert traces(body) == [2, 3, 4, 5]


def test_reference_parameter_default_na_and_explicit_values():
    assert traces(
        "read(array<float> a=na)=>na(a)?0:array.get(a,0)\na=array.new_float(1,close)\nplot(read())\nplot(read(a))"
    ) == [0, 1, 0, 2, 0, 3, 0, 4]


def test_local_collection_calls_do_not_share_persistent_state():
    body = "f(int step)=>\n    var a=array.new_int(1,0)\n    array.set(a,0,array.get(a,0)+step)\n    a\na=f(1)\nb=f(10)\nplot(a.get(0))\nplot(b.get(0))"
    assert traces(body) == [1, 10, 2, 20, 3, 30, 4, 40]


def test_same_function_in_loop_reuses_var_but_fresh_constructor_occurrences_do_not_collide():
    body = "f()=>\n    var a=array.new_int(1,0)\n    a.set(0,a.get(0)+1)\n    a\nint n=0\nfor i=0 to 2\n    fresh=array.new_int(1,i)\n    n:=array.get(f(),0)+fresh.get(0)\nplot(n)"
    assert traces(body) == [5, 8, 11, 14]


@pytest.mark.parametrize("expression", [False, True])
def test_reference_history_keeps_past_instances_not_repeated_identity(expression):
    body = (
        "a=array.new_float(1,close)[1]" if expression else "now=array.new_float(1,close)\na=now[1]"
    ) + "\nplot(na(a)?na:array.get(a,0))"
    out = traces(body)
    assert is_na(out[0]) and out[1:] == [1, 2, 3]


def test_history_of_persistent_alias_is_same_mutable_instance():
    out = traces("var a=array.new_float(1,0)\na.set(0,close)\nb=a[1]\nplot(na(b)?na:b.get(0))")
    assert is_na(out[0]) and out[1:] == [2, 3, 4]


def test_copy_and_slice_differ_and_each_allocation_is_fresh():
    body = "a=array.new_float(2,close)\nb=a.copy()\nc=a.slice(0,1)\nb.set(0,9)\nc.set(0,7)\nplot(a.get(0))\nplot(b.get(0))"
    assert traces(body) == [7, 9] * 4


@pytest.mark.parametrize("version", [5, 6])
def test_tuple_members_have_independent_history_and_missing_typed_defaults(version):
    out = traces(
        "[x,b]=if close>1\n    [close,true]\nplot(x)\nplot(b)\nplot(x[1])\nplot(b[1])",
        version=version,
    )
    assert is_na(out[0]) and is_na(out[2])
    assert (
        (out[1] is False and out[3] is False) if version == 6 else (is_na(out[1]) and is_na(out[3]))
    )
    assert out[4:6] == [2, True] and is_na(out[6])
    assert out[8:] == [3, True, 2, True, 4, True, 3, True]


def test_tuple_return_can_carry_a_reference_and_discarded_members():
    out = traces(
        "f(float x)=>[array.new_float(1,x),x>2]\n[a,_]=f(close)\nplot(a.get(0))\np=a[1]\nplot(na(p)?na:p.get(0))"
    )
    assert out[::2] == [1, 2, 3, 4] and is_na(out[1]) and out[3::2] == [1, 2, 3]


@pytest.mark.parametrize("indexed", [False, True])
def test_for_in_binds_values_indexes_and_observes_size_mutation(indexed):
    target = "[i,v]" if indexed else "v"
    term = "i+v" if indexed else "v"
    body = f"a=array.new_int(1,1)\nint n=0\nfor {target} in a\n    n+={term}\n    if a.size()<3\n        a.push(1)\nplot(n)"
    assert traces(body) == ([6] * 4 if indexed else [3] * 4)


@pytest.mark.parametrize("mutation", ["pop", "clear"])
def test_for_in_never_reads_beyond_mutated_length(mutation):
    body = f"a=array.new_int(3,1)\nint n=0\nfor v in a\n    n+=v\n    a.{mutation}()\nplot(n)"
    assert traces(body) == ([2] * 4 if mutation == "pop" else [1] * 4)


@pytest.mark.parametrize(
    "body",
    [
        "var a=array.new_float(1,0)\nf()=>\n    a:=array.new_float(1,1)\nf()",
        "f(array<float> a)=>array.get(a,0)\na=array.new_int(1,1)\nplot(f(a))",
        'a=array.new_float(1,0)\na.set(0,"not a number")',
        "var array<Unknown> a=na",
    ],
)
def test_unsupported_or_mistyped_references_do_not_compile_as_scalar_values(body):
    with pytest.raises((ValueError, RuntimeError)):
        compile_source(source(body))


@pytest.mark.parametrize("mode", ["var", "varip"])
def test_compiled_reference_rollback_on_open_ticks(mode):
    result = compile_source(
        source(f"{mode} a=array.new_int(1,0)\na.set(0,a.get(0)+1)\nplot(a.get(0))")
    )
    ns = {}
    exec(compile(result.emitted.code, "refs.py", "exec"), ns)
    r = RuntimeSession(
        RuntimeLanguageContext(6, "refs", "pine-v6", "sha256:" + "a" * 64, "compiler_annotation")
    )
    out = []
    for seq in range(4):
        tx = r.begin(
            CallbackFrame(
                "HISTORICAL_EVAL" if seq == 0 else "REALTIME_TICK",
                seq,
                realtime=seq > 0,
                final_tick=seq in (0, 3),
                bar_index=0 if seq == 0 else 1,
            ),
            values=BarValues(1, 2, 0, 1, 1, seq * 60000, (seq + 1) * 60000 - 1),
        )
        ns["GeneratedScript"](tx).run()
        # Values observed before provisional visual rollback are present in the working tape.
        tx.commit()
        rows = r.references.to_json()["objects"]
        out.append(from_portable(rows[0]["working"])[0])
    assert out == ([1, 2, 2, 2] if mode == "var" else [1, 2, 3, 4])
    restored = RuntimeSession(r.language)
    restored.restore(json.loads(json.dumps(r.checkpoint().to_dict())))
    assert restored.state_hash == r.state_hash


@pytest.mark.parametrize("kind", ["array", "map", "matrix"])
def test_compiled_checkpoint_restores_reference_parameters_and_histories(kind):
    bodies = {
        "array": "f(array<float> a)=>a[1]\na=array.new_float(1,close)\np=f(a)\nplot(na(p)?na:p.get(0))",
        "map": 'f(map<string,float> a)=>a[1]\na=map.new<string,float>()\na.put("x",close)\np=f(a)\nplot(na(p)?na:p.get("x"))',
        "matrix": "f(matrix<float> a)=>a[1]\na=matrix.new<float>(1,1,close)\np=f(a)\nplot(na(p)?na:p.get(0,0))",
    }
    body = bodies[kind]
    result = compile_source(source(body))
    ns = {}
    exec(compile(result.emitted.code, "refs.py", "exec"), ns)
    language = RuntimeLanguageContext(
        6, "refs", "pine-v6", "sha256:" + "a" * 64, "compiler_annotation"
    )

    def step(r, i):
        tx = r.begin(
            CallbackFrame("HISTORICAL_EVAL", i, bar_index=i),
            values=BarValues(i + 1, i + 2, i, i + 1, 1, i * 60000, (i + 1) * 60000 - 1),
        )
        ns["GeneratedScript"](tx).run()
        tx.commit()

    whole = RuntimeSession(language)
    for i in range(4):
        step(whole, i)
    prefix = RuntimeSession(language)
    for i in range(2):
        step(prefix, i)
    resumed = RuntimeSession(language)
    resumed.restore(json.loads(json.dumps(prefix.checkpoint().to_dict())))
    for i in range(2, 4):
        step(resumed, i)
    assert whole.checkpoint().to_dict() == resumed.checkpoint().to_dict()


@pytest.mark.parametrize("method", [False, True])
def test_concat_returns_the_first_array_identity(method):
    call = "a.concat(b)" if method else "array.concat(a,b)"
    assert (
        traces(
            f"a=array.new_float(1,close)\nb=array.new_float(1,7)\nc={call}\nc.set(0,9)\nplot(a.get(0))\nplot(a.size())"
        )
        == [9, 2] * 4
    )


@pytest.mark.parametrize(
    "body",
    [
        "a=array.new_float(1,close)\nplot(array.get(index=0,id=a))",
        'm=map.new<string,float>()\nmap.put(value=close,key="x",id=m)\nplot(map.get(key="x",id=m))',
        "m=matrix.new<float>(1,1,close)\nplot(matrix.get(column=0,row=0,id=m))",
    ],
)
def test_collection_receiver_type_follows_named_binding_not_source_order(body):
    assert traces(body) == [1, 2, 3, 4]
