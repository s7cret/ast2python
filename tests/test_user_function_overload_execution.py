"""Hand-derived executions, not a TradingView execution oracle."""

import json

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pinelib import CallbackFrame
from pinelib.state.checkpoint import from_portable

from ast2python import compile_consumer_bundle
from ast2python.lowering import load_pinelib_target_manifest
from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)


def compile_plain(body, version=6):
    bundle = build_consumer_bundle(
        script(body, imports="", version=version), producer_commit="a" * 40
    )
    return compile_consumer_bundle(
        bundle,
        target=load_pinelib_target_manifest(),
        producer_commit="b" * 40,
        expected_pine2ast_commit="a" * 40,
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "declarations,calls,expected",
    [
        ("f(int x)=>x+1\nf(float x)=>x+0.5", "plot(f(2))\nplot(f(2.0))", [3, 2.5]),
        ("f(x,y)=>x*y\nf(x,y,z)=>x*y*z", "plot(f(2,3))\nplot(f(2,3,4))", [6, 24]),
        ("f(float x)=>-x\nf(bool x)=>not x", "plot(f(true) ? 1 : 0)\nplot(f(2.5))", [0, -2.5]),
        (
            "f(int x,float scale=2.0)=>x*scale\nf(string x)=>str.length(x)",
            'plot(f(2))\nplot(f(scale=3.0,x=2))\nplot(f("abc"))',
            [4.0, 6.0, 3],
        ),
        ("f(int x)=>x+1\nf(int x,int y)=>f(x)+y", "plot(f(1,2))", [4]),
        (
            "f(int x)=>[x,x+1]\nf(float x)=>[x,x+0.5]",
            "[a,b]=f(2)\n[c,d]=f(2.0)\nplot(a+b+c+d)",
            [9.5],
        ),
        (
            "f(array<int> x)=>array.size(x)\nf(matrix<float> x)=>matrix.rows(x)",
            "plot(f(array.new<int>(2)))\nplot(f(matrix.new<float>(3,1,0.0)))",
            [2, 3],
        ),
    ],
)
def test_local_overloads_exact_values(version, declarations, calls, expected):
    c = compile_plain(declarations + "\n" + calls, version)
    runtime, cls = runtime_for(c)
    assert advance(runtime, cls, [1, 2, 3]) == expected * 3


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
def test_per_call_state_for_each_overload_and_checkpoint(version, imported):
    declarations = "f(int step)=>\n    var int n=0\n    n+=step\n    n\nf(float step)=>\n    var float n=0.0\n    n+=step\n    n"
    name = "lib.f" if imported else "f"
    body = f"plot({name}(1))\nplot({name}(10.0))\ns=0\nfor i=0 to 2\n    s:={name}(1)\nplot(s)"
    if imported:
        c, _ = compile_linked(
            script(body, version=version),
            {"user/Lib/1": library(declarations.replace("f(", "export f("), version=version)},
        )
    else:
        c = compile_plain(declarations + "\n" + body, version)
    whole, cls = runtime_for(c)
    assert advance(whole, cls, [1, 2, 3]) == [1, 10.0, 3, 2, 20.0, 6, 3, 30.0, 9]
    split, _ = runtime_for(c)
    advance(split, cls, [1])
    checkpoint = json.loads(json.dumps(split.checkpoint().to_dict()))
    restored, _ = runtime_for(c)
    restored.restore(checkpoint)
    advance(restored, cls, [2, 3], start=1)
    assert restored.checkpoint().to_dict() == whole.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
def test_private_more_specific_overload_does_not_leak_into_public_call(version):
    declarations = "f(int x)=>x+100\nexport f(float x)=>x+1\nexport g(int x)=>f(x)"
    c, _ = compile_linked(
        script("plot(lib.f(2))\nplot(lib.g(2))", version=version),
        {"user/Lib/1": library(declarations, version=version)},
    )
    runtime, cls = runtime_for(c)
    assert advance(runtime, cls, [1, 2, 3]) == [3.0, 102] * 3


@pytest.mark.parametrize("version", [5, 6])
def test_namespace_overload_sets_do_not_mix_between_modules(version):
    libs = {
        "u/A/1": library("export f(int x)=>x+1\nexport f(float x)=>x+0.5", "A", version),
        "u/B/1": library("export f(int x)=>x+10\nexport f(float x)=>x+20.0", "B", version),
    }
    c, _ = compile_linked(
        script(
            "plot(a.f(2))\nplot(a.f(2.0))\nplot(b.f(2))\nplot(b.f(2.0))",
            imports="import u/A/1 as a\nimport u/B/1 as b",
            version=version,
        ),
        libs,
    )
    runtime, cls = runtime_for(c)
    assert advance(runtime, cls, [1, 2]) == [3, 2.5, 12, 22.0] * 2


def compile_family(declarations, body, version, imported):
    if imported:
        return compile_linked(
            script(body, version=version), {"user/Lib/1": library(declarations, version=version)}
        )[0]
    return compile_plain(declarations.replace("export ", "") + "\n" + body, version)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
@pytest.mark.parametrize("kind", ["map", "udt", "enum", "color", "string", "array_float"])
def test_distinct_return_and_parameter_types_across_reference_families(version, imported, kind):
    ns = "lib." if imported else ""
    fixtures = {
        "map": (
            'export f(map<string,int> x)=>x.get("k")',
            'a=map.new<string,int>()\na.put("k",7)',
            "a",
            7,
        ),
        "udt": ("export type C\n    int n=7\nexport f(C x)=>x.n", f"a={ns}C.new()", "a", 7),
        "enum": (
            "export enum Side\n    up\n    down\nexport f(Side x)=>x==Side.up ? 7 : -7",
            f"a={ns}Side.down",
            "a",
            -7,
        ),
        "color": ("export f(color x)=>x==#070000 ? 7 : -7", "a=#070000", "a", 7),
        "string": ("export f(string x)=>str.length(x)", 'a="abcdefg"', "a", 7),
        "array_float": (
            "export f(array<float> x)=>x.get(0)",
            "a=array.new<float>(1,7.5)",
            "a",
            7.5,
        ),
    }
    decl, initial, value, expected = fixtures[kind]
    compiled = compile_family(
        decl + "\nexport f(int x)=>x+10",
        initial + f"\nplot({ns}f({value}))\nplot({ns}f(2))",
        version,
        imported,
    )
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1, 2]) == [expected, 12] * 2


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
def test_udt_overload_and_scalar_overload_keep_intrabar_field_policies(version, imported):
    ns = "lib." if imported else ""
    decl = "export type C\n    int bars=0\n    varip int ticks=0\nexport f(C self,int n)=>\n    self.bars+=n\n    self.ticks+=n\n    self\nexport f(int self)=>self+1"
    body = f"var {ns}C a={ns}C.new()\nvar {ns}C b={ns}C.new()\n{ns}f(a,1)\n{ns}f(n=10,self=b)\nplot(a.bars+b.bars)\nplot(a.ticks+b.ticks)\nplot({ns}f(2))"
    compiled = compile_family(decl, body, version, imported)
    original, cls = runtime_for(compiled)
    assert advance(original, cls, [1]) == [11, 11, 3]

    def tick(runtime, n, final):
        tx = runtime.begin(
            CallbackFrame("REALTIME_TICK", n, bar_index=1, realtime=True, final_tick=final)
        )
        cls(tx).run()
        values = [from_portable(e.payload["series"]) for e in runtime.visuals.working[-3:]]
        tx.commit()
        return values

    assert tick(original, 1, False) == [22, 22, 3]
    restored, _ = runtime_for(compiled)
    restored.restore(json.loads(json.dumps(original.checkpoint().to_dict())))
    for runtime in (original, restored):
        assert tick(runtime, 2, False) == [22, 33, 3]
        assert tick(runtime, 3, True) == [22, 44, 3]
    assert original.checkpoint().to_dict() == restored.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
def test_stateful_builtin_inside_overloads_keeps_input_length_and_history(version, imported):
    from pinelib import is_na

    ns = "lib." if imported else ""
    declarations = "export f(float x,simple int n)=>ta.sma(x,n)\nexport f(int x)=>x+10"
    c = compile_family(
        declarations, f"n=input.int(2)\nplot({ns}f(close,n))\nplot({ns}f(2))", version, imported
    )
    r, cls = runtime_for(c)
    out = advance(r, cls, [1, 2, 3])
    assert is_na(out[0]) and out[1:] == [12, 1.5, 12, 2.5, 12]
    r, cls = runtime_for(c, {"n": 3})
    out = advance(r, cls, [1, 2, 3])
    assert is_na(out[0]) and is_na(out[2]) and out[1::2] == [12] * 3 and out[4] == 2


@pytest.mark.parametrize("version", [5, 6])
def test_transitive_overloads_keep_source_unit_private_and_return_floors(version):
    libs = {
        "u/D/1": library("f(int x)=>x+100\nexport f(float x)=>x+1.5", "D", version),
        "user/Lib/1": library(
            "import u/D/1 as d\nexport g(int x)=>d.f(x)\nexport g(string x)=>str.length(x)",
            version=version,
        ),
    }
    c, _ = compile_linked(script('plot(lib.g(2))\nplot(lib.g("abc"))', version=version), libs)
    r, cls = runtime_for(c)
    assert advance(r, cls, [1, 2]) == [3.5, 3] * 2
    from pine2ast.hardening.consumer_bundle import ConsumerBundleError
    from pine2ast.libraries import LibraryError

    for body in ["plot(lib.f(2))", "n=input.int(lib.g(2))", "plot(d.f(2))"]:
        with pytest.raises((LibraryError, ConsumerBundleError)):
            compile_linked(script(body, version=version), libs)


@pytest.mark.parametrize("fault", ["symbol", "overload", "parameter", "actual_type", "capability"])
def test_rehashed_function_facts_cannot_change_the_selected_declaration(fault):
    from copy import deepcopy

    from pine2ast.hardening.consumer_bundle import ConsumerBundleError
    from pine2ast.libraries.store import canonical, source_hash

    from ast2python.errors import BundleInvariantError

    bundle = build_consumer_bundle(
        script("f(int x)=>x+1\nf(float x)=>x+100.0\nplot(f(2))", imports=""),
        producer_commit="a" * 40,
    )
    bad = deepcopy(bundle)
    row = next(c for c in bad["semantic_facts"]["calls"] if c["call_form"] == "USER_FUNCTION")
    if fault == "symbol":
        row["symbol_id"] = row["symbol_id"] + "bad"
    elif fault == "overload":
        row["overload_id"] = row["overload_id"] + "bad"
    elif fault == "parameter":
        row["arguments"][0]["parameter_name"] = "wrong"
    elif fault == "actual_type":
        row["arguments"][0]["actual_type"] = "float"
    else:
        bad["consumer_contract"]["required_capabilities"].remove("user_function_overloads_v1")
    bad["content_hash"] = source_hash(
        canonical({k: v for k, v in bad.items() if k != "content_hash"})
    )
    with pytest.raises((ConsumerBundleError, BundleInvariantError)):
        compile_consumer_bundle(
            bad,
            target=load_pinelib_target_manifest(),
            producer_commit="b" * 40,
            expected_pine2ast_commit="a" * 40,
        )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
@pytest.mark.parametrize("kind", ["udt", "array", "loop_tuple"])
def test_overload_returns_keep_alias_or_completed_loop_value(version, imported, kind):
    ns = "lib." if imported else ""
    if kind == "udt":
        decl = "export type C\n    int n=0\nexport f(C self)=>self\nexport f(int n)=>C.new(n)"
        body = f"a={ns}f(2)\nb={ns}f(a)\nb.n:=9\nplot(a.n)\nplot({ns}f(3).n)"
        expected = [9, 3]
    elif kind == "array":
        decl = "export f(array<int> self)=>self\nexport f(int n)=>array.new<int>(1,n)"
        body = f"a={ns}f(2)\nb={ns}f(a)\narray.set(b,0,9)\nplot(array.get(a,0))\nplot(array.get({ns}f(3),0))"
        expected = [9, 3]
    else:
        decl = "export f(int x)=>\n    for i=0 to 2\n        if i==2\n            break\n        [x+i,x+i+1]\nexport f(float x)=>[x,x+0.5]"
        body = f"[a,b]={ns}f(2)\n[c,d]={ns}f(2.0)\nplot(a)\nplot(b)\nplot(c)\nplot(d)"
        expected = [3, 4, 2.0, 2.5]
    c = compile_family(decl, body, version, imported)
    r, cls = runtime_for(c)
    assert advance(r, cls, [1, 2]) == expected * 2


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
def test_conditional_call_maintains_its_own_local_history(version, imported):
    ns = "lib." if imported else ""
    decl = "export f(int step)=>\n    var int n=0\n    n+=step\n    [n,n[1]]\nexport f(float step)=>step+0.5"
    # Preserve missing values through an admitted typed declaration. Numeric
    # cast builtins are outside this overload contract's binding scope.
    body = f"int absent=na\n[n,p]=if bar_index%2==0\n    {ns}f(1)\nelse\n    [absent,absent]\nplot(n)\nplot(p)\nplot({ns}f(2.0))"
    from pinelib import is_na

    c = compile_family(decl, body, version, imported)
    r, cls = runtime_for(c)
    out = advance(r, cls, [1, 2, 3, 4, 5])
    assert out[0] == 1 and is_na(out[1])
    assert all(is_na(out[i]) for i in [3, 4, 9, 10])
    assert out[6:9] == [2, 1, 2.5] and out[12:15] == [3, 2, 2.5]
    assert out[2::3] == [2.5] * 5
