"""Stage 2.3 exact-target execution for UDF lexical/callsite state."""

import json

import pytest
from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, is_na
from pinelib.errors import PineRuntimeError
from pinelib.runtime.metadata import BarValues
from pinelib.state.checkpoint import from_portable

from tests.test_rc6_input_metadata import compile_source, run_source


def source(body: str, version: int = 6) -> str:
    decl = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{decl}("stage23")\n{body}\n'


def values(runtime):
    return [from_portable(e.payload["series"]) for e in runtime.visuals.committed]


@pytest.mark.parametrize("version", [4, 5, 6])
def test_defaults_are_evaluated_inside_callee_lexical_scope(version):
    body = "f(int a=2,int b=a+1)=>b\nplot(f())\nplot(f(5))\nplot(f(a=7))"
    runtime, _, _ = run_source(source(body, version), closes=[1, 2])
    assert values(runtime) == [3, 6, 8] * 2


@pytest.mark.parametrize("version", [4, 5, 6])
def test_default_uses_definition_global_not_caller_shadow(version):
    body = "int BASE=2\ninner(int x=BASE)=>x\nouter()=>\n    int BASE=9\n    inner()\nplot(outer())"
    runtime, _, _ = run_source(source(body, version), closes=[1, 2])
    assert values(runtime) == [2, 2]


@pytest.mark.parametrize("version", [5, 6])
def test_stateful_default_expression_is_owned_by_written_outer_callsite(version):
    body = "f(float x=ta.sma(close,2))=>x\nplot(f())\nplot(f())"
    runtime, _, _ = run_source(source(body, version), closes=[1, 2, 3])
    out = values(runtime)
    assert is_na(out[0]) and is_na(out[1])
    assert out[2:] == [1.5, 1.5, 2.5, 2.5]


@pytest.mark.parametrize("version", [5, 6])
def test_nested_stateful_builtin_is_split_by_outer_written_calls(version):
    body = "inner(float x)=>ta.sma(x,2)\nouter(float x)=>inner(x)\nplot(outer(close))\nplot(outer(close*10))"
    runtime, _, _ = run_source(source(body, version), closes=[1, 2, 3])
    out = values(runtime)
    assert is_na(out[0]) and is_na(out[1])
    assert out[2:] == [1.5, 15.0, 2.5, 25.0]


@pytest.mark.parametrize("version", [4, 5, 6])
def test_skipped_udf_call_advances_local_history_only_on_executed_bars(version):
    body = (
        "f(int x)=>\n"
        "    var int n=0\n"
        "    n+=x\n"
        "    n[1]\n"
        "int a=na\n"
        "if bar_index!=1\n"
        "    a:=f(1)\n"
        "plot(a)"
    )
    runtime, _, _ = run_source(source(body, version), closes=[1, 2, 3, 4])
    out = values(runtime)
    assert is_na(out[0])
    assert is_na(out[1])
    assert out[2:] == [1, 2]


def _runtime():
    return RuntimeSession(
        RuntimeLanguageContext(6, "stage2", "pine-v6", "sha256:" + "a" * 64, "compiler_annotation")
    )


def _frame(seq: int, close: float):
    return (
        CallbackFrame("HISTORICAL_EVAL", seq, bar_index=seq),
        BarValues(close, close, close, close, 1, seq * 60000, (seq + 1) * 60000 - 1),
    )


def test_udf_failure_unwinds_call_path_and_abort_rolls_back_local_state():
    compiled = compile_source(
        source("f(float x)=>\n    var int n=0\n    n+=1\n    z=1/x\n    n\nplot(f(close-1))")
    )
    ns = {}
    exec(compiled.emitted.code, ns)
    cls = ns["GeneratedScript"]
    runtime = _runtime()

    frame, bars = _frame(0, 1)
    tx = runtime.begin(frame, values=bars)
    with pytest.raises(PineRuntimeError, match="division by zero"):
        cls(tx).run()
    assert tx._function_path == ()
    tx.abort()

    frame, bars = _frame(1, 2)
    tx = runtime.begin(frame, values=bars)
    cls(tx).run()
    tx.commit()
    assert values(runtime)[-1] == 1

    saved = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    restored = _runtime()
    restored.restore(saved)
    frame, bars = _frame(2, 3)
    for obj in (runtime, restored):
        tx = obj.begin(frame, values=bars)
        cls(tx).run()
        tx.commit()
    assert runtime.checkpoint().to_dict() == restored.checkpoint().to_dict()
    assert values(runtime)[-1] == 2


@pytest.mark.parametrize(
    "mode,expected_ticks",
    [
        ("var", ([2, 20], [2, 20], [2, 20])),
        ("varip", ([2, 20], [3, 30], [4, 40])),
    ],
)
def test_udf_local_var_and_varip_have_distinct_realtime_lifetimes(mode, expected_ticks):
    compiled = compile_source(
        source(f"f(int step)=>\n    {mode} int n=0\n    n+=step\n    n\nplot(f(1))\nplot(f(10))")
    )
    ns = {}
    exec(compiled.emitted.code, ns)
    cls = ns["GeneratedScript"]
    runtime = _runtime()

    frame, bars = _frame(0, 1)
    tx = runtime.begin(frame, values=bars)
    cls(tx).run()
    tx.commit()
    assert values(runtime)[-2:] == [1, 10]

    def tick(seq: int, final: bool):
        bars = BarValues(2, 2, 2, 2, 1, 60000, 119999)
        tx = runtime.begin(
            CallbackFrame("REALTIME_TICK", seq, bar_index=1, realtime=True, final_tick=final),
            values=bars,
        )
        cls(tx).run()
        current = [from_portable(e.payload["series"]) for e in runtime.visuals.working[-2:]]
        tx.commit()
        return current

    assert tick(1, False) == list(expected_ticks[0])
    assert tick(2, False) == list(expected_ticks[1])
    assert tick(3, True) == list(expected_ticks[2])


@pytest.mark.parametrize("version", [4, 5, 6])
def test_parameter_history_is_independent_per_written_callsite(version):
    body = "f(float x)=>x[1]\nplot(f(close))\nplot(f(close*10))"
    runtime, _, _ = run_source(source(body, version), closes=[1, 2, 3])
    out = values(runtime)
    assert is_na(out[0]) and is_na(out[1])
    assert out[2:] == [1.0, 10.0, 2.0, 20.0]


@pytest.mark.parametrize("version", [4, 5, 6])
def test_branch_written_calls_keep_independent_local_state(version):
    body = (
        "f()=>\n"
        "    var int n=0\n"
        "    n+=1\n"
        "    n\n"
        "int a=0\n"
        "if bar_index%2==0\n"
        "    a:=f()\n"
        "else\n"
        "    a:=f()\n"
        "plot(a)"
    )
    runtime, _, _ = run_source(source(body, version), closes=[1, 2, 3, 4, 5])
    assert values(runtime) == [1, 1, 2, 2, 3]


@pytest.mark.parametrize("version", [4, 5, 6])
def test_udf_result_history_is_runtime_series_not_python_local(version):
    body = "f(float x)=>x*2\nplot(f(close)[1])"
    runtime, _, _ = run_source(source(body, version), closes=[1, 2, 3])
    out = values(runtime)
    assert is_na(out[0])
    assert out[1:] == [2.0, 4.0]
