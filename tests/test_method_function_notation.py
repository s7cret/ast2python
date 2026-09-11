"""Method syntax is not a second execution engine.

Expectations are hand-derived from method bodies. There is no recorded TradingView
execution oracle here. Existing callsite/rollback/reference owners are exercised.
"""
from copy import deepcopy
import json

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle, ConsumerBundleError
from pine2ast.hardening.method_functions import METHOD_FUNCTION_CAPABILITY
from pine2ast.libraries import LibraryError
from pine2ast.libraries.store import canonical, source_hash
from pinelib import CallbackFrame
from pinelib.state.checkpoint import from_portable

from ast2python import compile_consumer_bundle
from ast2python.errors import BundleInvariantError
from ast2python.lowering import load_pinelib_target_manifest
from tests.test_locked_library_execution import advance, compile_linked, library, runtime_for, script


def compile_form(body, declarations, version=6, imported=True):
    if imported:
        return compile_linked(script(body, version=version), {
            "user/Lib/1": library(declarations, version=version)
        })
    bundle = build_consumer_bundle(
        f'//@version={version}\nindicator("explicit receiver")\n'
        + declarations.replace("export ", "") + "\n" + body + "\n",
        producer_commit="a" * 40,
    )
    compiled = compile_consumer_bundle(
        bundle, target=load_pinelib_target_manifest(), producer_commit="b" * 40,
        expected_pine2ast_commit="a" * 40,
    )
    return compiled, None


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
@pytest.mark.parametrize("kind", ["int", "float", "array", "map", "matrix", "udt", "enum"])
def test_function_notation_and_dot_share_receiver_types_and_state(version, imported, kind):
    ns = "lib." if imported else ""
    fixtures = {
        "int": ("a=2", "export method get(simple int self,int delta=3)=>self+delta", 5),
        "float": ("a=2.5", "export method get(simple float self,int delta=3)=>self+delta", 5.5),
        "array": ("a=array.new<float>(2,7)", "export method get(array<float> self)=>self.get(1)", 7),
        "map": ('a=map.new<string,int>()\na.put("key",7)', 'export method get(map<string,int> self)=>self.get("key")', 7),
        "matrix": ("a=matrix.new<int>(2,2,7)", "export method get(matrix<int> self)=>self.get(0,1)", 7),
        "udt": (f"a={ns}P.new(7)", "export type P\n    int n=0\nexport method get(P self)=>self.n", 7),
        "enum": (f"a={ns}Side.down", "export enum Side\n    up\n    down\nexport method get(Side self)=>self==Side.up ? 1 : -1", -1),
    }
    init, decl, value = fixtures[kind]
    compiled, _ = compile_form(init+f"\nplot({ns}get(a))\nplot(a.get())", decl, version, imported)
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1, 2]) == [value, value] * 2
    assert METHOD_FUNCTION_CAPABILITY not in compiled.plan.required_capabilities


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
def test_named_receiver_not_first_and_default_bind_exact_declaration(version, imported):
    ns = "lib." if imported else ""
    decl = "export method plus(simple int self,int n=3)=>self+n\nexport method plus(simple float item,float n=0.5)=>item+n"
    compiled, _ = compile_form(
        f"plot({ns}plus(n=4,self=2))\nplot({ns}plus(item=2.5))\nplot({ns}plus(self=2))",
        decl, version, imported,
    )
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1, 2]) == [6, 3, 5] * 2


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
def test_mixed_notation_keeps_written_callsites_and_same_call_in_loop(version, imported):
    ns = "lib." if imported else ""
    decl = "export method count(int self)=>\n    var int n=0\n    n+=self\n    n"
    body = f"a=10\nplot({ns}count(1))\nplot(a.count())\nn=0\nfor i=0 to 2\n    n:={ns}count(1)\nplot(n)"
    compiled, _ = compile_form(body, decl, version, imported)
    whole, cls = runtime_for(compiled)
    expected = [1, 10, 3, 2, 20, 6, 3, 30, 9]
    assert advance(whole, cls, [1, 2, 3]) == expected
    split, _ = runtime_for(compiled)
    assert advance(split, cls, [1]) == expected[:3]
    saved = json.loads(json.dumps(split.checkpoint().to_dict()))
    restored, _ = runtime_for(compiled)
    restored.restore(saved)
    assert advance(restored, cls, [2, 3], 1) == expected
    assert restored.checkpoint().to_dict() == whole.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
def test_explicit_udt_receiver_retains_fields_varip_and_midbar_restore(version, imported):
    ns = "lib." if imported else ""
    decl = "export type C\n    int bars=0\n    varip int ticks=0\nexport method step(C self,int n)=>\n    self.bars+=n\n    self.ticks+=n\n    self"
    body = f"var {ns}C a={ns}C.new()\nvar {ns}C b={ns}C.new()\n{ns}step(n=1,self=a)\nb.step(10)\nplot(a.bars+b.bars)\nplot(a.ticks+b.ticks)"
    compiled, _ = compile_form(body, decl, version, imported)
    original, cls = runtime_for(compiled)
    assert advance(original, cls, [1]) == [11, 11]
    def tick(runtime, n, final):
        tx = runtime.begin(CallbackFrame("REALTIME_TICK", n, bar_index=1, realtime=True, final_tick=final))
        cls(tx).run()
        values = [from_portable(e.payload["series"]) for e in runtime.visuals.working[-2:]]
        tx.commit()
        return values
    assert tick(original, 1, False) == [22, 22]
    saved = json.loads(json.dumps(original.checkpoint().to_dict()))
    restored, _ = runtime_for(compiled)
    restored.restore(saved)
    for runtime in (original, restored):
        assert tick(runtime, 2, False) == [22, 33]
        assert tick(runtime, 3, True) == [22, 44]
    assert original.checkpoint().to_dict() == restored.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("notation", ["function", "method", "imported"])
def test_named_arguments_are_evaluated_once_in_written_order(version, notation):
    # Receiver is written last, so it observes 2, then 4, then 6. No wrapper or
    # repeated receiver evaluation may change these manually derived numbers.
    decl = "export type C\n    int n=0\nexport method take(C self)=>\n    self.n+=1\n    self.n\n"
    ns = "lib." if notation == "imported" else ""
    imported = notation == "imported"
    decl += ("export combine(int self,int other)=>self*10+other" if notation == "function"
             else "export method combine(int self,int other)=>self*10+other")
    body = f"var {ns}C c={ns}C.new()\nplot({ns}combine(other={ns}take(c),self={ns}take(c)))\nplot(c.n)"
    compiled, _ = compile_form(body, decl, version, imported)
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1, 2, 3]) == [21, 2, 43, 4, 65, 6]


@pytest.mark.parametrize("version", [5, 6])
def test_qualified_import_selects_library_not_import_order_or_same_method_name(version):
    libs = {f"u/{name}/1": library(f"export method plus(simple int self)=>self+{delta}",name,version)
            for name,delta in [("A",1),("B",10)]}
    for imports in ["import u/A/1 as a\nimport u/B/1 as b", "import u/B/1 as b\nimport u/A/1 as a"]:
        compiled, _ = compile_linked(script("plot(a.plus(2))\nplot(b.plus(2))",imports,version), libs)
        runtime, cls = runtime_for(compiled)
        assert advance(runtime, cls, [1,2]) == [3,12]*2
        with pytest.raises(LibraryError):
            compile_linked(script("n=2\nplot(n.plus())",imports,version), libs)


@pytest.mark.parametrize("version", [5, 6])
def test_transitive_explicit_calls_and_private_bare_helpers_do_not_leak(version):
    libs = {
        "u/D/1": library("export method deep(simple int self)=>self+10","D",version),
        "user/Lib/1": library("import u/D/1 as d\nmethod hidden(simple int self)=>d.deep(self)+1\nexport method outer(simple int self)=>hidden(self)",version=version),
    }
    compiled, _ = compile_linked(script("plot(lib.outer(2))",version=version), libs)
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1,2]) == [13,13]
    for call in ["lib.hidden(2)", "lib.deep(2)", "hidden(2)", "deep(2)"]:
        with pytest.raises((LibraryError, ConsumerBundleError)):
            compile_linked(script(f"plot({call})",version=version),libs)


@pytest.mark.parametrize("fault", ["missing_capability", "extra_capability", "receiver", "parameter", "actual_type"])
def test_explicit_receiver_bundle_replay_rejects_forged_facts(fault):
    text='//@version=6\nindicator("sealed")\nmethod plus(simple int self,int n=1)=>self+n\nplot(plus(2,n=3))\n'
    bundle = build_consumer_bundle(text,producer_commit="a"*40)
    bad = deepcopy(bundle)
    if fault == "missing_capability":
        bad["consumer_contract"]["required_capabilities"].remove(METHOD_FUNCTION_CAPABILITY)
    elif fault == "extra_capability":
        bad["consumer_contract"]["required_capabilities"].append("unsupported_method_v999")
    else:
        calls = bad["semantic_facts"]["calls"]
        call = next(c for c in calls if c["call_form"] == "USER_METHOD")
        if fault == "receiver": call["receiver_type"]="float"
        elif fault == "parameter": call["arguments"][0]["parameter_name"]="n"
        else: call["arguments"][0]["actual_type"]="string"
    bad["content_hash"]=source_hash(canonical({k:v for k,v in bad.items() if k!="content_hash"}))
    with pytest.raises((ConsumerBundleError, BundleInvariantError)):
        compile_consumer_bundle(bad,target=load_pinelib_target_manifest(),producer_commit="b"*40,expected_pine2ast_commit="a"*40)


@pytest.mark.parametrize("version", [5, 6])
def test_namespace_call_followed_by_dot_and_builtin_call_has_distinct_source_identity(version):
    decl = "export method plus(simple int self,simple int n=1)=>self+n\nexport method feed(array<float> self,float x)=>\n    self.push(x)\n    self"
    body = "a=array.new<float>()\nplot(lib.plus(2).plus())\nplot(lib.feed(a,7).size())\nplot(lib.plus(lib.plus(2)))"
    compiled, _ = compile_linked(script(body,version=version), {"user/Lib/1":library(decl,version=version)})
    runtime, cls = runtime_for(compiled)
    assert advance(runtime,cls,[1,2]) == [4,1,4]*2
