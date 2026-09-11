"""Pinned public methods use the ordinary compiler and runtime state machinery.

Expected values are hand-calculated fixtures, not exports from TradingView.
"""

import json
from copy import deepcopy

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.libraries import LibraryError
from pinelib import CallbackFrame, is_na
from pinelib.state.checkpoint import from_portable

from ast2python import compile_consumer_bundle
from ast2python.errors import BundleInvariantError
from ast2python.lowering import load_pinelib_target_manifest
from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body,decl,expected",
    [
        (
            "a=2\nplot(a.plus(step=3))",
            "export method plus(simple int self,simple int step=1)=>self+step",
            [5],
        ),
        (
            "a=2\nb=2.5\nplot(a.plus())\nplot(b.plus())",
            "export method plus(simple int self)=>self+1\nexport method plus(simple float self)=>self+10",
            [3, 12.5],
        ),
        ("a=2\nplot(a.plus().plus())", "export method plus(simple int self)=>self+1", [4]),
        (
            "a=2\nplot(a.public())",
            "method secret(simple int self)=>self+7\nexport method public(simple int self)=>self.secret()",
            [9],
        ),
        (
            "p=lib.Point.new(2)\nplot(p.plus(3))",
            "export type Point\n    int n=0\nexport method plus(Point self,int step=1)=>self.n+step",
            [5],
        ),
        (
            "s=lib.Side.down\nplot(s.number())",
            "export enum Side\n    up\n    down\nexport method number(Side self)=>self==Side.up ? 1 : -1",
            [-1],
        ),
        (
            "a=2\nplot(a.plus())",
            "method_plus(simple int x)=>x+10\nexport method plus(simple int self)=>method_plus(self)",
            [12],
        ),
    ],
)
def test_public_methods_overloads_defaults_chain_and_nominal_receiver(
    version, body, decl, expected
):
    compiled, linked = compile_linked(
        script(body, version=version), {"user/Lib/1": library(decl, version=version)}
    )
    assert linked.receipt()["profile"] == "same_version_methods_v5"
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1, 2, 3]) == expected * 3
    assert "library_method_projection_v1" not in compiled.plan.required_capabilities


@pytest.mark.parametrize("version", [5, 6])
def test_private_methods_keep_module_scope_and_written_state(version):
    libs = {
        "u/A/1": library(
            "method hidden(simple int self)=>self+1\nexport method first(simple int self)=>self.hidden()",
            "A",
            version,
        ),
        "u/B/1": library(
            "method hidden(simple int self)=>self+10\nexport method second(simple int self)=>self.hidden()",
            "B",
            version,
        ),
    }
    src = script(
        "method hidden(simple int self)=>self+100\nn=2\nplot(n.first())\nplot(n.second())\nplot(n.hidden())",
        "import u/A/1 as a\nimport u/B/1 as b",
        version,
    )
    compiled, _ = compile_linked(src, libs)
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1, 2]) == [3, 12, 102] * 2


@pytest.mark.parametrize("version", [5, 6])
def test_stateful_method_calls_and_same_call_in_loop_restore(version):
    decl = "export method count(simple int self)=>\n    var int n=0\n    n+=self\n    n"
    src = script(
        "a=1\nb=10\nplot(a.count())\nplot(b.count())\ns=0\nfor i=0 to 2\n    s:=a.count()\nplot(s)",
        version=version,
    )
    compiled, _ = compile_linked(src, {"user/Lib/1": library(decl, version=version)})
    whole, cls = runtime_for(compiled)
    expected = [1, 10, 3, 2, 20, 6, 3, 30, 9]
    assert advance(whole, cls, [1, 2, 3]) == expected
    split, _ = runtime_for(compiled)
    advance(split, cls, [1])
    saved = json.loads(json.dumps(split.checkpoint().to_dict()))
    resumed, _ = runtime_for(compiled)
    resumed.restore(saved)
    assert advance(resumed, cls, [2, 3], start=1) == expected
    assert resumed.checkpoint().to_dict() == whole.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
def test_array_receiver_reference_return_chain_and_independent_ta(version):
    decl = "export method feed(array<float> self,float x)=>\n    self.push(x)\n    self\nexport method avg(float self,simple int n=2)=>ta.sma(self,n)"
    src = script(
        "var array<float> a=array.new<float>()\nx=a.feed(close).size()\nplot(x)\nplot(close.avg())\nplot(close.avg(3))",
        version=version,
    )
    compiled, _ = compile_linked(src, {"user/Lib/1": library(decl, version=version)})
    runtime, cls = runtime_for(compiled)
    values = advance(runtime, cls, [1, 2, 3])
    assert values[0::3] == [1, 2, 3]
    assert is_na(values[1]) and values[4::3] == [1.5, 2.5]
    assert is_na(values[2]) and is_na(values[5]) and values[8] == 2


@pytest.mark.parametrize("version", [5, 6])
def test_exported_udt_method_field_varip_rollback_and_midbar_restore(version):
    decl = (
        "export type C\n    int bars=0\n    varip int ticks=0\n"
        "export method step(C self,int n)=>\n    self.bars+=n\n    self.ticks+=n\n    self"
    )
    src = script(
        "var lib.C a=lib.C.new()\nvar lib.C b=lib.C.new()\na.step(1)\nb.step(10)\nplot(a.bars+b.bars)\nplot(a.ticks+b.ticks)",
        version=version,
    )
    compiled, _ = compile_linked(src, {"user/Lib/1": library(decl, version=version)})
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [11, 11]

    def tick(session, sequence, final):
        tx = session.begin(
            CallbackFrame("REALTIME_TICK", sequence, bar_index=1, realtime=True, final_tick=final)
        )
        cls(tx).run()
        values = [from_portable(e.payload["series"]) for e in session.visuals.working[-2:]]
        tx.commit()
        return values

    assert tick(runtime, 1, False) == [22, 22]
    saved = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    restored, _ = runtime_for(compiled)
    restored.restore(saved)
    for session in (runtime, restored):
        assert tick(session, 2, False) == [22, 33]
        assert tick(session, 3, True) == [22, 44]
    assert runtime.checkpoint().to_dict() == restored.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
def test_transitive_methods_and_same_named_types_remain_bound_to_source(version):
    libs = {
        "u/D/1": library("export method deep(simple int self)=>self+10", "D", version),
        "user/Lib/1": library(
            "import u/D/1 as d\nexport method outer(simple int self)=>self.deep()+1",
            version=version,
        ),
    }
    compiled, _ = compile_linked(script("a=2\nplot(a.outer())", version=version), libs)
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [13]
    with pytest.raises(LibraryError):
        compile_linked(script("a=2\nplot(a.deep())", version=version), libs)
    libs = {
        name: library(
            f"export type P\n    int n={n}\nexport method value(P self)=>self.n",
            name.split("/")[1],
            version,
        )
        for name, n in [("u/A/1", 1), ("u/B/1", 10)]
    }
    compiled, _ = compile_linked(
        script(
            "p=a.P.new()\nq=b.P.new()\nplot(p.value())\nplot(q.value())",
            "import u/A/1 as a\nimport u/B/1 as b",
            version,
        ),
        libs,
    )
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [1, 10]


def test_source_invalidation_and_artifact_context_capability_are_mandatory():
    decl = "export method plus(simple int self)=>self+1"
    src = script("a=2\nplot(a.plus())")
    first, linked = compile_linked(src, {"user/Lib/1": library(decl)})
    changed, _ = compile_linked(src, {"user/Lib/1": library(decl.replace("self+1", "self+10"))})
    assert (
        first.artifact.payload["build_determinism_identity"]
        != changed.artifact.payload["build_determinism_identity"]
    )
    for compiled, expected in [(first, 3), (changed, 12)]:
        runtime, cls = runtime_for(compiled)
        assert advance(runtime, cls, [1]) == [expected]
    bundle = build_consumer_bundle(linked.code, producer_commit="a" * 40, linked_source=linked)
    damaged = deepcopy(bundle)
    damaged["consumer_contract"]["required_capabilities"].remove("library_method_projection_v1")
    from pine2ast.libraries.store import canonical, source_hash

    damaged["content_hash"] = source_hash(
        canonical({k: v for k, v in damaged.items() if k != "content_hash"})
    )
    with pytest.raises((ConsumerBundleError, BundleInvariantError)):
        compile_consumer_bundle(
            damaged,
            linked_source=linked,
            target=load_pinelib_target_manifest(),
            producer_commit="b" * 40,
            expected_pine2ast_commit="a" * 40,
        )


@pytest.mark.parametrize(
    "call", ["close.plus()", "bar_index.plus()", "a=2\nb=a.fixed()\nn=input.int(b)"]
)
def test_method_receiver_and_exported_result_qualifiers_are_not_downgraded(call):
    decl = "export method plus(simple int self)=>self+1\nexport method fixed(simple int self)=>7"
    with pytest.raises((LibraryError, ConsumerBundleError, BundleInvariantError)):
        compile_linked(script(call), {"user/Lib/1": library(decl)})


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["map", "matrix", "void_array"])
def test_other_collection_receivers_and_void_statements(version, kind):
    if kind == "map":
        decl = (
            "export method bump(map<string,int> self,int n)=>\n"
            '    old=self.contains("n") ? self.get("n") : 0\n'
            '    self.put("n",old+n)\n    self.get("n")'
        )
        body = "var map<string,int> a=map.new<string,int>()\nplot(a.bump(1))"
    elif kind == "matrix":
        decl = (
            "export method bump(matrix<int> self,int n)=>\n"
            "    self.set(0,0,self.get(0,0)+n)\n    self.get(0,0)"
        )
        body = "var matrix<int> a=matrix.new<int>(1,1,0)\nplot(a.bump(1))"
    else:
        decl = "export method feed(array<float> self,float x)=>self.push(x)"
        body = "var array<float> a=array.new<float>()\na.feed(close)\nplot(a.size())"
    compiled, _ = compile_linked(
        script(body, version=version), {"user/Lib/1": library(decl, version=version)}
    )
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1, 2, 3]) == [1, 2, 3]


@pytest.mark.parametrize("version", [5, 6])
def test_library_method_argument_evaluation_order_is_unchanged(version):
    decl = (
        "next(array<int> self)=>\n    self.set(0,self.get(0)+1)\n    self.get(0)\n"
        "export method digits(array<int> self)=>next(self)*10+next(self)"
    )
    body = "var array<int> a=array.new<int>(1,0)\nplot(a.digits())"
    compiled, _ = compile_linked(
        script(body, version=version), {"user/Lib/1": library(decl, version=version)}
    )
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1, 2, 3]) == [12, 34, 56]
