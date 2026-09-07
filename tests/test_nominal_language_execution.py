"""Hand-derived nominal type and method results in real generated Pine code."""

import json
from dataclasses import replace

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pinelib import CallbackFrame, is_na
from pinelib.state.checkpoint import from_portable

from ast2python import BundleInvariantError, compile_consumer_bundle
from ast2python.lowering import load_pinelib_target_manifest
from tests.test_locked_library_execution import runtime_for
from tests.test_rc6_input_metadata import compile_source, run_source


def source(body, version=6):
    return f'//@version={version}\n{"indicator" if version >= 5 else "study"}("nominal")\n{body}\n'


def trace(body, version=6, closes=(1, 2, 3)):
    runtime, _, _ = run_source(source(body, version), closes=closes)
    return [from_portable(event.payload["series"]) for event in runtime.visuals.committed]


@pytest.mark.parametrize("version", [5, 6])
def test_udt_defaults_field_updates_aliases_and_shallow_copy(version):
    body = (
        "type Point\n    int x=3\n    array<int> values\n"
        "a=array.new<int>(1,5)\np=Point.new(values=a)\n"
        "alias=p\nq=p.copy()\nalias.x+=2\nq.x:=10\n"
        "array.set(q.values,0,7)\nplot(p.x)\nplot(q.x)\nplot(array.get(p.values,0))"
    )
    assert trace(body, version) == [5, 10, 7] * 3


@pytest.mark.parametrize("version", [5, 6])
def test_udt_implicit_defaults_are_versioned(version):
    out = trace("type P\n    bool flag\n    int n\np=P.new()\nplot(p.flag)\nplot(na(p.n))", version)
    assert (
        all(value is False for value in out[::2])
        if version == 6
        else all(is_na(value) for value in out[::2])
    )
    assert out[1::2] == [True] * 3


@pytest.mark.parametrize("version", [5, 6])
def test_udt_array_map_returns_and_reference_history(version):
    body = (
        "type P\n    float n\nidentity(P x)=>x\n"
        "p=P.new(close)\na=array.new<P>(1,p)\nm=map.new<string,P>()\n"
        'map.put(m,"p",array.get(a,0))\nq=identity(map.get(m,"p"))\n'
        "q.n+=10\nprevious=p[1]\nplot(q.n)\nplot(na(previous) ? -1 : previous.n)"
    )
    assert trace(body, version) == [11, -1, 12, 11, 13, 12]


@pytest.mark.parametrize("version", [5, 6])
def test_enum_switch_udt_fields_parameters_returns_and_history(version):
    body = (
        "enum Side\n    buy\n    sell\n"
        "type Order\n    Side side=Side.buy\n"
        "identity(Side side)=>side\no=Order.new()\n"
        "o.side:=close>1 ? Side.sell : Side.buy\ne=identity(o.side)\n"
        "n=switch e\n    Side.buy => 10\n    Side.sell => 20\n"
        "plot(n)\nplot(e[1]==Side.buy)"
    )
    out = trace(body, version)
    assert out[::2] == [10, 20, 20]
    assert out[3::2] == [True, False]
    assert out[1] is False if version == 6 else is_na(out[1])


@pytest.mark.parametrize("version", [5, 6])
def test_methods_resolve_exact_nominal_and_generic_receivers(version):
    body = (
        "type A\n    int n=1\ntype B\n    int n=10\n"
        "method score(A self,int step=2)=>self.n+step\n"
        "method score(B self,int step=3)=>self.n*step\n"
        "method score(array<int> self,int step=4)=>array.size(self)+step\n"
        "method score(array<string> self,int step=5)=>array.size(self)*step\n"
        'a=A.new()\nb=B.new()\nc=array.new<int>(2)\nd=array.new<string>(3,"")\n'
        "plot(a.score())\nplot(b.score(step=4))\nplot(c.score())\nplot(d.score())"
    )
    assert trace(body, version) == [3, 40, 6, 15] * 3


@pytest.mark.parametrize("version", [5, 6])
def test_method_state_is_per_written_call_and_reused_in_loop(version):
    body = (
        "type P\n    int n=0\nmethod count(P self,int step=1)=>\n"
        "    var int count=0\n    count+=step\n    self.n:=count\n    self\n"
        "p=P.new()\nq=P.new()\na=0\nfor i=1 to 3\n    r=p.count()\n    a:=r.n\n"
        "s=q.count(step=2)\nplot(a)\nplot(s.n)"
    )
    assert trace(body, version) == [3, 2, 6, 4, 9, 6]


@pytest.mark.parametrize("version", [5, 6])
def test_nominal_loop_values_and_field_assignment_result(version):
    body = (
        "enum E\n    a\n    b\ntype P\n    int n=0\n"
        "p=for i=1 to 3\n    if i==3\n        break\n    P.new(i)\n"
        "e=for i=1 to 3\n    if i==3\n        continue\n    i==1 ? E.a : E.b\n"
        "n=for i=1 to 3\n    p.n+=1\n"
        "plot(n)\nplot(p.n)\nplot(e==E.b)"
    )
    assert trace(body, version) == [5, 5, True] * 3


@pytest.mark.parametrize("version", [5, 6])
def test_udt_namespace_copy_and_method_return_history(version):
    body = (
        "type P\n    float n\nmethod identity(P self)=>self\n"
        "p=P.new(close)\nq=P.copy(object=p)\nq.n+=10\n"
        "previous=q.identity()[1]\nplot(na(previous) ? -1 : previous.n)"
    )
    assert trace(body, version) == [-1, 11, 12]


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize(
    "body", ["type P\n    int n=0", "enum Side\n    buy", "method score(int self)=>self"]
)
def test_nominal_and_method_wrong_versions_are_rejected(version, body):
    with pytest.raises(ConsumerBundleError):
        compile_source(source(body, version))


@pytest.mark.parametrize(
    "body",
    [
        "enum A\n    x\nenum B\n    x\nplot(A.x==B.x)",
        "enum A\n    x\na=A.unknown",
        "type P\n    int n\np=P.new(unknown=1)",
        'type P\n    int n\np=P.new(n="wrong")',
        "type P\n    int n\np=P.new()\np.missing:=1",
        "type P\n    int n\ntype Q\n    int n\nmethod score(P self)=>self.n\nq=Q.new()\nplot(q.score())",
    ],
)
def test_nominal_type_errors_are_rejected_before_execution(body):
    with pytest.raises(ConsumerBundleError):
        compile_source(source(body))


def test_nominal_emission_requires_explicit_runtime_contract():
    target = load_pinelib_target_manifest()
    target = replace(target, capabilities=target.capabilities - {"compiler.nominal_types.v1"})
    with pytest.raises(BundleInvariantError, match="A2P_PLAN_CAPABILITY"):
        compile_consumer_bundle(
            build_consumer_bundle(source("enum E\n    a\ne=E.a")), target=target
        )


def callback(
    runtime, cls, sequence, bar, *, realtime=False, final=True, phase=None, deferred=False
):
    tx = runtime.begin(
        CallbackFrame(
            phase or ("REALTIME_TICK" if realtime else "HISTORICAL_EVAL"),
            sequence,
            bar_index=bar,
            realtime=realtime,
            final_tick=final,
            defer_bar_commit=deferred,
        )
    )
    cls(tx).run()
    values = [from_portable(event.payload["series"]) for event in runtime.visuals.working[-2:]]
    tx.commit()
    return values


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("binding", ["var", "varip"])
def test_udt_field_rollback_checkpoint_and_enum_state(version, binding):
    body = (
        "enum E\n    a\n    b\ntype P\n    int ordinary=0\n    varip int ticks=0\n"
        f"{binding} P p=P.new()\nvar E e=E.a\n"
        "p.ordinary+=1\np.ticks+=1\ne:=E.b\nplot(p.ordinary)\nplot(p.ticks)"
    )
    compiled = compile_source(source(body, version))
    runtime, cls = runtime_for(compiled)
    assert callback(runtime, cls, 0, 0) == [1, 1]
    assert callback(runtime, cls, 1, 1, realtime=True, final=False) == [2, 2]
    assert callback(runtime, cls, 2, 1, realtime=True, final=False) == [2, 3]
    assert callback(runtime, cls, 3, 1, realtime=True) == [2, 4]
    restored, _ = runtime_for(compiled)
    restored.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
    for session in (runtime, restored):
        assert callback(session, cls, 4, 2, realtime=True, final=False) == [3, 5]
        assert callback(session, cls, 5, 2, realtime=True) == [3, 6]
    assert runtime.checkpoint().to_dict() == restored.checkpoint().to_dict()


def test_once_historical_fill_rollback_then_closed_bar_checkpoint():
    # Independent specification: once uses an ordinary var completion flag;
    # execution-model docs explicitly permit rollback on historical order fills.
    # Intrabar n escapes rollback, ordinary and the gate do not. Only the final
    # bar commit makes the completion permanent. See the investigation receipt.
    body = "varip int n=0\nvar int ordinary=0\nonce\n    n+=1\n    ordinary+=1\nplot(n)\nplot(ordinary)"
    compiled = compile_source(source(body))
    runtime, cls = runtime_for(compiled)
    assert callback(runtime, cls, 0, 0, deferred=True) == [1, 1]
    assert callback(runtime, cls, 1, 0, phase="ORDER_FILL_RECALC", deferred=True) == [2, 1]
    runtime.finalize_bar(0)
    restored, _ = runtime_for(compiled)
    restored.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
    for session in (runtime, restored):
        assert callback(session, cls, 3, 1, deferred=True) == [2, 1]
        assert callback(session, cls, 4, 1, phase="ORDER_FILL_RECALC", deferred=True) == [2, 1]
        session.finalize_bar(1)
    assert runtime.checkpoint().to_dict() == restored.checkpoint().to_dict()
