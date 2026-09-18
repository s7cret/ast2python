"""Stage 2.7 generated-path matrix for if/switch/loop values and once rollback."""

from __future__ import annotations

import json

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError
from pinelib.state.checkpoint import from_portable

from tests.test_nominal_language_execution import callback, runtime_for, source
from tests.test_rc6_input_metadata import compile_source, run_source


def traces(body, *, version=6, closes=(1, 2, 3)):
    runtime, _, _ = run_source(source(body, version), closes=closes)
    return [from_portable(event.payload["series"]) for event in runtime.visuals.committed]


@pytest.mark.parametrize("version", [5, 6])
def test_stage27_if_and_switch_return_last_completed_value(version):
    body = (
        "a=if close>1\n    10\nelse\n    20\n"
        "b=switch close>1\n    true => 3\n    false => 4\n"
        "plot(a)\nplot(b)"
    )
    out = traces(body, version=version)
    assert out[0::2] == [20, 10, 10]
    assert out[1::2] == [4, 3, 3]


@pytest.mark.parametrize("version", [5, 6])
def test_stage27_for_break_continue_zero_iterations_and_nested(version):
    body = (
        "empty=array.new<int>()\n"
        "z=for x in empty\n    x\n"
        "n=0\n"
        "for i=1 to 4\n    if i==2\n        continue\n    if i==4\n        break\n    n:=n+i\n"
        "m=0\n"
        "for i=1 to 2\n    for j=1 to 2\n        m:=m+1\n"
        "plot(na(z) ? -1 : z)\nplot(n)\nplot(m)"
    )
    out = traces(body, version=version, closes=(1,))
    assert out == [-1, 4, 4]


@pytest.mark.parametrize("version", [5, 6])
def test_stage27_for_in_array_map_and_udt_enum_loop_results(version):
    body = (
        "enum Side\n    buy\n    sell\n"
        "type Box\n    int n=0\n"
        "xs=array.new<int>(3, 0)\narray.set(xs,0,1)\narray.set(xs,1,2)\narray.set(xs,2,3)\n"
        "a=for x in xs\n    x\n"
        'm=map.new<string,int>()\nmap.put(m,"a",10)\nmap.put(m,"b",20)\n'
        "k=for [key, val] in m\n    val\n"
        "box=for i=1 to 2\n    Box.new(i)\n"
        "side=for i=1 to 2\n    i==1 ? Side.buy : Side.sell\n"
        "plot(a)\nplot(k)\nplot(box.n)\nplot(side==Side.sell)"
    )
    out = traces(body, version=version, closes=(1,))
    assert out[0] == 3
    assert out[1] == 20
    assert out[2] == 2
    assert out[3] is True


@pytest.mark.parametrize("version", [5, 6])
def test_stage27_while_scalar_assignments(version):
    body = "i=0\na=0\nb=0\nwhile i<2\n    i+=1\n    a:=i\n    b:=i*10\nplot(a)\nplot(b)"
    out = traces(body, version=version, closes=(1,))
    assert out == [2, 20]


@pytest.mark.parametrize("version", [5, 6])
def test_stage27_while_and_tuple_loop_value(version):
    assert traces(
        "i=0\n[a,b]=while i<2\n    i+=1\n    [i,i*10]\nplot(a)\nplot(b)",
        version=version,
        closes=(1,),
    ) == [2, 20]


@pytest.mark.parametrize("version", [5, 6])
def test_stage27_tuple_loop_break_continue_and_empty(version):
    body = (
        "i=0\n[a,b]=while i<5\n    i+=1\n    if i==2\n        continue\n"
        "    if i==4\n        break\n    [i,i*10]\n"
        "[x,y]=while false\n    [1,2]\nplot(a)\nplot(b)\nplot(na(x))\nplot(na(y))"
    )
    assert traces(body, version=version, closes=(1,)) == [3, 30, True, True]


def test_stage27_once_completes_once_and_survives_later_bars():
    out = traces("var int n=0\nonce\n    n+=1\nplot(n)", version=6, closes=(1, 2, 3))
    assert out == [1, 1, 1]


def test_stage27_once_unfinal_tick_rolls_back_completion():
    # No historical execution pre-completes the once slot. varip is a witness:
    # a re-execution increments ticks, while ordinary state rolls back.
    compiled = compile_source(
        source(
            "varip int ticks=0\nvar int ordinary=0\nonce\n    ticks+=1\n    ordinary+=1\nplot(ticks)\nplot(ordinary)"
        )
    )
    runtime, cls = runtime_for(compiled)
    assert callback(runtime, cls, 0, 0, realtime=True, final=False) == [1, 1]
    assert callback(runtime, cls, 1, 0, realtime=True, final=False) == [2, 1]
    assert callback(runtime, cls, 2, 0, realtime=True, final=True) == [3, 1]
    portable = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    restored, _ = runtime_for(compiled)
    restored.restore(portable)
    for session in (runtime, restored):
        assert callback(session, cls, 3, 1, realtime=True, final=False) == [3, 1]
        assert callback(session, cls, 4, 1, realtime=True, final=True) == [3, 1]
    assert runtime.checkpoint().to_dict() == restored.checkpoint().to_dict()


def test_stage27_once_not_an_expression():
    with pytest.raises(ConsumerBundleError):
        compile_source(source("x=once\n    1\nplot(x)"))
