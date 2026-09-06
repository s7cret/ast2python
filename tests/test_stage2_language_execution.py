"""Versioned scalar/control semantics through the exact generated-Pine path.

Expectations are hand-derived, not generated from OpenPine output or a TV oracle.
"""

import json

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError
from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, is_na
from pinelib.runtime.metadata import BarValues
from pinelib.state.checkpoint import from_portable

from tests.test_rc6_input_metadata import compile_source, run_source


def source(body, version=6):
    return f'//@version={version}\n{"indicator" if version >= 5 else "study"}("language")\n{body}\n'


def traces(body, *, version=6, closes=(1, 2, 3, 4)):
    runtime, _, _ = run_source(source(body, version), closes=closes)
    return [from_portable(event.payload["series"]) for event in runtime.visuals.committed]


@pytest.mark.parametrize("version", [3, 4, 5, 6])
@pytest.mark.parametrize("value", ["true", "1", "1.5"])
def test_missing_if_branch_has_versioned_typed_default(version, value):
    # v3 has no explicit type annotations, inferred typed branch still works.
    out = traces(f"a=if close>2\n    {value}\nplot(a)", version=version)
    if version == 6 and value == "true":
        assert out[:2] == [False, False]
    else:
        assert all(is_na(x) for x in out[:2])
    assert out[2:] == [{"true": True, "1": 1, "1.5": 1.5}[value]] * 2


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("selector", [False, True])
def test_switch_block_returns_and_bool_default(version, selector):
    branch = "close\n    3" if selector else "\n    close==3"
    out = traces(
        "a=switch " + branch + " =>\n        bool x=true\n        x\nplot(a)", version=version
    )
    assert out[2] is True
    if version == 6:
        assert out[0] is False and out[3] is False
    else:
        assert is_na(out[0]) and is_na(out[3])


@pytest.mark.parametrize("version", range(1, 7))
def test_expression_history_uses_bool_type_and_canonical_na(version):
    out = traces("plot((close>2)[1])", version=version)
    assert out[0] is False if version == 6 else is_na(out[0])
    assert out[1:] == [False, False, True]


@pytest.mark.parametrize("version", [3, 4, 5, 6])
def test_function_ending_in_conditional_returns_value(version):
    parameter = "float x" if version >= 4 else "x"
    out = traces(
        f"f({parameter})=>\n    if x>2\n        x+1\n    else\n        x-1\nplot(f(close))",
        version=version,
    )
    assert out == [0, 1, 4, 5]


@pytest.mark.parametrize("version", [4, 5, 6])
def test_function_call_paths_are_independent_and_defaults_bound(version):
    out = traces(
        "f(int step=1)=>\n    var int n=0\n    n:=n+step\n    n\nplot(f())\nplot(f(step=2))",
        version=version,
    )
    assert out == [1, 2, 2, 4, 3, 6, 4, 8]


@pytest.mark.parametrize("version", [4, 5, 6])
def test_same_written_function_in_loop_reuses_state(version):
    out = traces(
        "f()=>\n    var int n=0\n    n:=n+1\n    n\na=0\nfor i=1 to 3\n    a:=f()\nplot(a)",
        version=version,
    )
    assert out == [3, 6, 9, 12]


@pytest.mark.parametrize("version", [4, 5, 6])
def test_nested_written_calls_have_independent_paths(version):
    out = traces(
        "f()=>\n    var int n=0\n    n:=n+1\n    n\ng()=>f()\nplot(g())\nplot(g())", version=version
    )
    assert out == [1, 1, 2, 2, 3, 3, 4, 4]


@pytest.mark.parametrize("version", [5, 6])
def test_ta_inside_two_function_calls_does_not_share_accumulator(version):
    out = traces("f(float x)=>ta.sma(x,2)\nplot(f(close))\nplot(f(close*10))", version=version)
    assert all(is_na(v) for v in out[:2])
    assert out[2:] == [1.5, 15.0, 2.5, 25.0, 3.5, 35.0]


@pytest.mark.parametrize("version", [4, 5, 6])
def test_local_history_clock_is_per_executed_bar_not_per_loop(version):
    body = (
        "f(float p)=>\n    p[1]\nfloat a=na\nif close!=2\n"
        "    for i=0 to 1\n        a:=f(close+i)\nplot(a)"
    )
    out = traces(body, version=version)
    assert all(is_na(v) for v in out[:2])
    assert out[2:] == [2, 4]


@pytest.mark.parametrize("mode", ["var", "varip"])
def test_function_local_once_has_distinct_callsite_state(mode):
    body = (
        f"f(int step)=>\n    {mode} int n=0\n    once\n        n+=step\n    n\n"
        "plot(f(1))\nplot(f(2))"
    )
    assert traces(body) == [1, 2] * 4


def test_once_does_not_evaluate_condition_again_after_completion():
    out = traces("var int n=0\nonce 1/(close-1)>0\n    n+=1\nplot(n)", closes=[2, 1, 1])
    assert out == [1, 1, 1]


@pytest.mark.parametrize("version", [4, 5, 6])
def test_shadowed_locals_and_globals_have_lexical_identity(version):
    body = (
        "int x=1\nint a=0\nif close>0\n    var int x=10\n    x:=x+1\n    a:=x\n"
        "if close>0\n    var int x=20\n    x:=x+2\n    a:=a+x\nplot(a)\nplot(x)"
    )
    assert traces(body, version=version) == [33, 1, 36, 1, 39, 1, 42, 1]


@pytest.mark.parametrize("version", [3, 4, 5, 6])
@pytest.mark.parametrize("start,stop,step,total", [(3, 1, 1, 6), (1, 3, 1, 6), (5, 1, 2, 9)])
def test_inclusive_ranges_auto_direction_and_continue(version, start, stop, step, total):
    body = f"n=0\nfor i={start} to {stop} by {step}\n    n:=n+i\nplot(n)"
    assert traces(body, version=version) == [total] * 4


@pytest.mark.parametrize("version", [5, 6])
def test_dynamic_end_is_only_reevaluated_in_v6(version):
    body = "int n=0\nint bound=1\nfor i=0 to bound\n    n+=1\n    bound:=2\nplot(n)"
    assert traces(body, version=version) == [3 if version == 6 else 2] * 4


@pytest.mark.parametrize("version", [3, 4, 5, 6])
def test_short_circuit_respects_version_instead_of_always_python_lazy(version):
    body = "a=false and (1/(close-close)>0)\nplot(a ? 1 : 0)"
    if version < 6:
        from pinelib.errors import PineRuntimeError

        with pytest.raises(PineRuntimeError, match="division by zero"):
            traces(body, version=version)
    else:
        assert traces(body, version=version) == [0] * 4


@pytest.mark.parametrize("version", range(1, 7))
def test_ternary_respects_documented_v3_v4_evaluation_change(version):
    # TradingView v4 release notes, July-August 2019: both branches in v3;
    # selected branch only from v4. This is distinct from v6 logical laziness.
    body = "a=false ? 1/(close-close) : 2\nplot(a)"
    if version < 4:
        from pinelib.errors import PineRuntimeError

        with pytest.raises(PineRuntimeError, match="division by zero"):
            traces(body, version=version)
    else:
        assert traces(body, version=version) == [2] * 4


@pytest.mark.parametrize("version", [4, 5])
def test_na_literal_predicate_and_bool_na_are_not_none_truthiness(version):
    out = traces("bool b=na\nplot(na(b) ? 1 : 0)\nplot(b ? 1 : 0)", version=version)
    assert out == [1, 0] * 4


@pytest.mark.parametrize("bad", ["bool b=na", "if 1\n    a=1", "x=na(true)", "x=nz(true)"])
def test_v6_invalid_bool_forms_still_fail_before_execution(bad):
    with pytest.raises(ConsumerBundleError):
        compile_source(source(bad))


def test_conditional_value_reassignment_keeps_enclosing_scalar_history():
    body = "int n=1\nx=if close>2\n    n:=n+1\n    n\nelse\n    n\nplot(n)\nplot(n[1])"
    out = traces(body)
    assert out[::2] == [1, 1, 2, 2]
    assert is_na(out[1]) and out[3::2] == [1, 1, 2]


@pytest.mark.parametrize("close_condition", [False, True])
def test_compiled_once_realtime_and_portable_continuation(close_condition):
    src = source("varip int n=0\nonce close>0\n    n+=1\nplot(n)")
    compiled = compile_source(src)
    ns = {}
    exec(compiled.emitted.code, ns)

    def runtime():
        return RuntimeSession(
            RuntimeLanguageContext(
                6, "stage2", "pine-v6", "sha256:" + "a" * 64, "compiler_annotation"
            )
        )

    s = runtime()
    sequence = [(0, 0, False, True), (1, 1, True, False), (1, int(close_condition), True, True)]
    for seq, (bar, c, rt, final) in enumerate(sequence):
        t = s.begin(
            CallbackFrame(
                "REALTIME_TICK" if rt else "HISTORICAL_EVAL",
                seq,
                bar_index=bar,
                realtime=rt,
                final_tick=final,
            ),
            values=BarValues(c, c + 1, c - 1, c, 1, bar * 60000, (bar + 1) * 60000 - 1),
        )
        ns["GeneratedScript"](t).run()
        t.commit()
    restored = runtime()
    restored.restore(json.loads(json.dumps(s.checkpoint().to_dict())))
    for obj in (s, restored):
        t = obj.begin(
            CallbackFrame("HISTORICAL_EVAL", 3, bar_index=2),
            values=BarValues(1, 2, 0, 1, 1, 120000, 179999),
        )
        ns["GeneratedScript"](t).run()
        t.commit()
    assert s.state_hash == restored.state_hash
    assert [from_portable(e.payload["series"]) for e in s.visuals.committed][-1] == 2


@pytest.mark.parametrize("version", [3, 4, 5, 6])
def test_block_returns_final_declaration_and_reassignment(version):
    body = "f(x)=>\n    y=x+1\ng(x)=>\n    y=x\n    y:=y+2\nplot(f(close))\nplot(g(close))"
    assert traces(body, version=version) == [2, 3, 3, 4, 4, 5, 5, 6]


def test_standalone_switch_executes_only_its_selected_arm():
    body = "int x=0\nswitch\n    close>2 => x:=10\n    => x:=20\nplot(x)"
    assert traces(body) == [20, 20, 10, 10]


def test_conditional_final_local_declaration_is_a_value():
    assert traces("x=if close>2\n    y=9\nelse\n    z=4\nplot(x)") == [4, 4, 9, 9]
