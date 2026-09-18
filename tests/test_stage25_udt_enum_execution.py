"""Stage 2.5 generated-path matrix for UDT/enum values, containers and errors."""

from __future__ import annotations

import json

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError
from pinelib.state.checkpoint import from_portable

from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)
from tests.test_nominal_language_execution import source, trace
from tests.test_rc6_input_metadata import compile_source, run_source


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_constructor_defaults_field_write_copy_and_history(version):
    body = (
        "type Point\n    int x=3\n    int y=4\n"
        "p=Point.new()\nalias=p\nq=p.copy()\n"
        "alias.x:=7\nq.y:=9\n"
        "prev=p[1]\nplot(p.x)\nplot(q.x)\nplot(q.y)\nplot(na(prev) ? -1 : prev.x)"
    )
    out = trace(body, version)
    assert out[0::4] == [7, 7, 7]
    assert out[1::4] == [3, 3, 3]
    assert out[2::4] == [9, 9, 9]
    assert out[3] == -1
    assert out[7] == 7


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_udt_in_array_map_args_returns_and_checkpoint(version):
    body = (
        "type Box\n    int n=0\n"
        "wrap(Box x)=>x\n"
        "p=Box.new(int(close))\n"
        "xs=array.new<Box>(1,p)\n"
        "m=map.new<string,Box>()\n"
        'map.put(m,"p",array.get(xs,0))\n'
        'q=wrap(map.get(m,"p"))\n'
        "q.n+=10\nplot(q.n)"
    )
    runtime, _, compiled = run_source(source(body, version), closes=(1, 2, 3))
    values = [from_portable(event.payload["series"]) for event in runtime.visuals.committed]
    assert values == [11, 12, 13]
    portable = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    restored, _, _ = run_source(source(body, version), closes=())
    restored.restore(portable)
    assert json.dumps(restored.checkpoint().to_dict()) == json.dumps(portable)


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_enum_switch_udt_field_and_versioned_missing_history(version):
    body = (
        "enum Side\n    buy\n    sell\n"
        "type Order\n    Side side=Side.buy\n"
        "echo(Side side)=>side\n"
        "o=Order.new()\n"
        "o.side:=close>1 ? Side.sell : Side.buy\n"
        "n=switch echo(o.side)\n    Side.buy => 1\n    Side.sell => 2\n"
        "prev=o[1]\nplot(n)\nplot(na(prev) ? false : prev.side==Side.buy)"
    )
    out = trace(body, version)
    assert out[::2] == [1, 2, 2]
    if version == 6:
        assert out[1] is False
    else:
        assert out[1] is not True


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_two_libraries_keep_same_named_types_and_enums_apart(version):
    libs = {
        "ownerA/Same/1": library(
            "export type Point\n    int n=1\nexport enum Side\n    one",
            name="Same",
            version=version,
        ),
        "ownerB/Same/1": library(
            "export type Point\n    int n=10\nexport enum Side\n    one",
            name="Same",
            version=version,
        ),
    }
    imports = "import ownerA/Same/1 as a\nimport ownerB/Same/1 as b"
    compiled, _ = compile_linked(
        script("p=a.Point.new()\nq=b.Point.new()\nplot(p.n)\nplot(q.n)", imports, version),
        libs,
    )
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [1, 10]
    descriptors = {entry["type_descriptor"] for entry in runtime.references.to_json()["objects"]}
    assert len(descriptors) == 2
    with pytest.raises(ConsumerBundleError):
        compile_linked(script("plot(a.Side.one==b.Side.one)", imports, version), libs)


@pytest.mark.parametrize(
    "body",
    [
        "enum A\n    x\nenum B\n    x\nplot(A.x==B.x)",
        "enum A\n    x\na=A.missing",
        "type P\n    int n\np=P.new(unknown=1)",
        "type P\n    int n\np=P.new()\np.missing:=1",
        '//@version=4\nstudy("old")\ntype P\n    int n',
    ],
)
def test_stage25_illegal_udt_enum_forms_rejected_before_execution(body):
    src = body if body.startswith("//@") else source(body)
    with pytest.raises(ConsumerBundleError):
        compile_source(src)


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_nested_udt_copy_shares_child_and_keeps_outer_identity(version):
    body = (
        "type Child\n    int n=1\n"
        "type Box\n    Child child\n"
        "c=Child.new()\nb=Box.new(c)\nclone=b.copy()\n"
        "clone.child.n:=9\n"
        "plot(b.child.n)\nplot(clone.child.n)"
    )
    assert trace(body, version) == [9, 9] * 3


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_udt_method_self_receiver_and_state(version):
    body = (
        "type Acc\n    int n=0\n"
        "method add(Acc self, int step=1)=>\n    var int seen=0\n    seen+=step\n    self.n:=seen\n    self.n\n"
        "a=Acc.new()\nb=Acc.new()\n"
        "plot(a.add())\nplot(b.add(2))\nplot(a.add())"
    )
    # Two written a.add() callsites keep independent state.
    assert trace(body, version) == [1, 2, 1, 2, 4, 2, 3, 6, 3]


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_field_varip_survives_unfinal_tick_ordinary_does_not(version):
    body = (
        "type P\n    int ordinary=0\n    varip int ticks=0\n"
        "var P p=P.new()\n"
        "p.ordinary+=1\np.ticks+=1\nplot(p.ordinary)\nplot(p.ticks)"
    )
    compiled = compile_source(source(body, version))
    runtime, cls = runtime_for(compiled)
    from tests.test_nominal_language_execution import callback

    assert callback(runtime, cls, 0, 0) == [1, 1]
    assert callback(runtime, cls, 1, 1, realtime=True, final=False) == [2, 2]
    assert callback(runtime, cls, 2, 1, realtime=True, final=False) == [2, 3]
    assert callback(runtime, cls, 3, 1, realtime=True) == [2, 4]


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_exported_enum_titles_and_members_roundtrip(version):
    libs = {
        "user/Lib/1": library(
            'export enum Side\n    buy="Buy"\n    sell="Sell"\nexport echo(Side s)=>s',
            version=version,
        )
    }
    compiled, _ = compile_linked(
        script(
            "s=lib.echo(lib.Side.sell)\nplot(s==lib.Side.sell)\nplot(s==lib.Side.buy)",
            version=version,
        ),
        libs,
    )
    runtime, cls = runtime_for(compiled)
    out = advance(runtime, cls, [1])
    assert out == [True, False]


@pytest.mark.parametrize(
    "body",
    [
        "type P\n    int n\ntype Q\n    int n\np=P.new()\nq=Q.new()\np:=q",
        "type P\n    int n\np=P.new()\np.n:=1.5",
        "enum Side\n    buy\nplot(Side.buy==1)",
    ],
)
def test_stage25_type_mismatches_rejected_on_generated_path(body):
    with pytest.raises(ConsumerBundleError):
        compile_source(source(body))
