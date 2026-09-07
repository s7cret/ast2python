"""Audited Pine builtins execute through exact versioned compiler/ABI bindings.

Expected values are elementary arithmetic or the documented EMA/RMA recurrences,
never snapshots produced by the compiler or runtime under test.
"""

import json
import math

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError
from pinelib import CallbackFrame, is_na
from pinelib.runtime.metadata import BarValues
from pinelib.state.checkpoint import from_portable

from ast2python.errors import BundleInvariantError
from tests.test_locked_library_execution import advance, runtime_for
from tests.test_rc6_input_metadata import compile_source, run_source


def source(body, version):
    declaration = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{declaration}("builtin contracts")\n{body}\n'


def builtin(name, version, namespace="math"):
    return f"{namespace}.{name}" if version >= 5 else name


def values(runtime):
    return [from_portable(event.payload["series"]) for event in runtime.visuals.committed]


def assert_numbers(actual, expected):
    assert len(actual) == len(expected)
    for got, wanted in zip(actual, expected, strict=True):
        if wanted is None:
            assert is_na(got)
        else:
            assert not is_na(got)
            assert got == pytest.approx(wanted, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("version", range(1, 7))
def test_exp_exact_named_parameter_and_udf_path(version):
    exp = builtin("exp", version)
    parameter = "number" if version >= 5 else "x"
    body = (
        f"f(x)=>{exp}({parameter}=x)\n"
        f"plot({exp}({parameter}=close))\nplot(f(close))\nplot(f(-close))"
    )
    if version == 1:
        body = f"plot({exp}({parameter}=close))\nplot({exp}(close))\n" f"plot({exp}(-close))"
    runtime, _, _ = run_source(source(body, version), closes=[0, 1, -1])
    assert_numbers(
        values(runtime), [1, 1, 1, math.e, math.e, 1 / math.e, 1 / math.e, 1 / math.e, math.e]
    )


@pytest.mark.parametrize("version", range(1, 7))
def test_audited_sqrt_pow_aliases_use_exact_named_parameters(version):
    sqrt = builtin("sqrt", version)
    power = builtin("pow", version)
    sqrt_parameter = "number" if version >= 5 else "x"
    power_parameters = "base=close,exponent=2"
    body = f"plot({sqrt}({sqrt_parameter}=close))\nplot({power}({power_parameters}))"
    if version >= 2:
        body = f"f(x)=>{sqrt}(x)\ng(x)=>{power}(x,2)\n{body}\nplot(f(close))\nplot(g(close))"
    runtime, _, _ = run_source(source(body, version), closes=[0, 1, 4, 9])
    expected = [(0, 0), (1, 1), (2, 16), (3, 81)]
    assert_numbers(
        values(runtime),
        [value for pair in expected for value in (pair * (2 if version >= 2 else 1))],
    )


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize(
    "name,expected",
    [
        ("sma", [None, None, 7 / 3, 14 / 3, 28 / 3]),
        ("wma", [None, None, 17 / 6, 17 / 3, 34 / 3]),
    ],
)
def test_audited_moving_average_aliases_and_udf_state(version, name, expected):
    call = builtin(name, version, "ta")
    body = f"plot({call}(source=close,length=3))"
    if version >= 2:
        body = f"f(x)=>{call}(x,3)\n{body}\nplot(f(close))\nplot(f(-close))"
    runtime, _, _ = run_source(source(body, version), closes=[1, 2, 4, 8, 16])
    if version >= 2:
        expected = [
            item for value in expected for item in (value, value, None if value is None else -value)
        ]
    assert_numbers(values(runtime), expected)


@pytest.mark.parametrize("version", range(1, 7))
def test_exp_and_round_propagate_typed_na(version):
    exp, rounding = builtin("exp", version), builtin("round", version)
    # Explicit float() was introduced in v4. Before v4, the numeric builtin's
    # parameter supplies the type for na; the expected propagation is unchanged.
    number = "float(na)" if version >= 4 else "na"
    runtime, _, _ = run_source(
        source(f"plot({exp}({number}))\nplot({rounding}({number}))", version), closes=[1]
    )
    assert all(is_na(value) for value in values(runtime))


@pytest.mark.parametrize("version", range(1, 7))
def test_abs_numeric_overloads_and_ceil_floor_exact_scalar_contracts(version):
    absolute, ceiling, floor = (builtin(name, version) for name in ("abs", "ceil", "floor"))
    name = "number" if version >= 5 else "x"
    body = (
        f"plot({absolute}({name}=-2))\nplot({absolute}({name}=-2.0))\n"
        f"plot({ceiling}({name}=close))\nplot({floor}({name}=close))"
    )
    runtime, _, _ = run_source(source(body, version), closes=[-1.5, -0.5, 0.5, 1.5])
    assert_numbers(values(runtime), [2, 2.0, -1, -2, 2, 2.0, 0, -1, 2, 2.0, 1, 0, 2, 2.0, 2, 1])
    assert [type(value) for value in values(runtime)] == [int, float, int, int] * 4


@pytest.mark.parametrize("version", [4, 5, 6])
def test_round_ties_and_precision_have_distinct_return_types(version):
    round_call = builtin("round", version)
    parameter = "number" if version >= 5 else "x"
    body = (
        f"f(x)=>{round_call}(x)\ng(x)=>{round_call}(x,0)\n"
        f"plot({round_call}({parameter}=close))\nplot(f(close))\n"
        f"plot({round_call}({parameter}=close,precision=0))\nplot(g(close))\n"
        f"plot({round_call}({parameter}=close,precision=1))"
    )
    runtime, _, _ = run_source(source(body, version), closes=[-1.5, -0.5, 0.5, 1.5])
    expected = [(-1, -1.5), (0, -0.5), (1, 0.5), (2, 1.5)]
    actual = values(runtime)
    assert_numbers(
        actual,
        [
            item
            for integer, decimal in expected
            for item in (integer, integer, float(integer), float(integer), decimal)
        ],
    )
    for start in range(0, len(actual), 5):
        assert [type(value) for value in actual[start : start + 5]] == [
            int,
            int,
            float,
            float,
            float,
        ]


@pytest.mark.parametrize("version", [1, 2, 3])
def test_early_round_integer_ties_and_unavailable_precision(version):
    runtime, _, _ = run_source(
        source("plot(round(x=close))", version), closes=[-1.5, -0.5, 0.5, 1.5]
    )
    assert values(runtime) == [-1, 0, 1, 2]
    assert all(type(value) is int for value in values(runtime))
    with pytest.raises(ConsumerBundleError):
        compile_source(source("plot(round(close,0))", version))


def test_v1_user_function_syntax_is_unavailable():
    with pytest.raises(ConsumerBundleError):
        compile_source(source("f(x)=>exp(x)\nplot(f(close))", 1))


CLOSES = [1, 2, 3, 2, 4, 3]
RSI = [None, None, 100, 50, 250 / 3, 50]
INVERSE_RSI = [None, None, 0, 50, 50 / 3, 50]
# Historical v3/v4 reference explicitly seeds EMA with SMA(length). These
# fractions are derived from EMA2 alpha=2/3, EMA3 alpha=1/2, signal EMA2.
HISTORICAL_MACD = [
    (None, None, None),
    (None, None, None),
    (1 / 2, None, None),
    (1 / 6, 1 / 3, -1 / 6),
    (7 / 18, 10 / 27, 1 / 54),
    (7 / 54, 17 / 81, -13 / 162),
]
# After four zero samples, fast/slow/signal are all zero under either disputed
# modern initialization rule. This table asserts the subsequent recurrence;
# it does not certify modern EMA/MACD warmup. See STAGE2_BUILTIN_BINDINGS.md.
ZERO_SEEDED_MACD = [
    (1 / 6, 1 / 9, 1 / 18),
    (11 / 36, 13 / 54, 7 / 108),
    (85 / 216, 37 / 108, 11 / 216),
    (143 / 1296, 365 / 1944, -301 / 3888),
    (2797 / 7776, 3527 / 11664, 1337 / 23328),
    (5351 / 46656, 4135 / 23328, -973 / 15552),
]


def rsi_body(version):
    rsi = builtin("rsi", version, "ta")
    named = "source=close,length=2" if version >= 5 else "x=close,y=2"
    if version == 1:
        return f"plot({rsi}({named}))\nplot({rsi}(close,2))\nplot({rsi}(-close,2))"
    return f"f(x)=>{rsi}(x,2)\nplot({rsi}({named}))\nplot(f(close))\nplot(f(-close))"


@pytest.mark.parametrize("version", range(1, 7))
def test_rsi_rma_seed_and_independent_udf_callsites(version):
    compiled = compile_source(source(rsi_body(version), version))
    runtime, cls = runtime_for(compiled)
    expected = [
        item
        for value, inverse in zip(RSI, INVERSE_RSI, strict=True)
        for item in (value, value, inverse)
    ]
    assert_numbers(advance(runtime, cls, CLOSES), expected)
    split, _ = runtime_for(compiled)
    advance(split, cls, CLOSES[:3])
    resumed, _ = runtime_for(compiled)
    resumed.restore(json.loads(json.dumps(split.checkpoint().to_dict())))
    assert_numbers(advance(resumed, cls, CLOSES[3:], start=3), expected)
    assert resumed.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", range(3, 7))
def test_macd_three_results_exact_length_binding_and_udf_path(version):
    macd = builtin("macd", version, "ta")
    body = (
        f"f(x)=>{macd}(x,2,3,2)\n"
        f"[a,b,c]={macd}(source=close,fastlen=2,slowlen=3,siglen=2)\n"
        "[d,e,fv]=f(close)\n"
        "plot(a)\nplot(b)\nplot(c)\nplot(d)\nplot(e)\nplot(fv)"
    )
    compiled = compile_source(source(body, version))
    runtime, cls = runtime_for(compiled)
    prefix = 4 if version >= 5 else 0
    closes = [0] * prefix + CLOSES
    table = ZERO_SEEDED_MACD if prefix else HISTORICAL_MACD
    expected = [value for triple in table for value in (*triple, *triple)]
    assert_numbers(advance(runtime, cls, closes)[prefix * 6 :], expected)
    split, _ = runtime_for(compiled)
    boundary = prefix + 3
    advance(split, cls, closes[:boundary])
    resumed, _ = runtime_for(compiled)
    resumed.restore(json.loads(json.dumps(split.checkpoint().to_dict())))
    assert_numbers(advance(resumed, cls, closes[boundary:], start=boundary)[prefix * 6 :], expected)
    assert resumed.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [1, 2])
def test_early_macd_executes_without_unavailable_tuple_declaration(version):
    runtime, _, result = run_source(
        source("macd(close,2,3,2)\nplot(close)", version), closes=CLOSES
    )
    assert values(runtime) == CLOSES
    assert "import macd_v1 as " in result.emitted.code


@pytest.mark.parametrize("version", [4, 6])
@pytest.mark.parametrize("phase", ["REALTIME_TICK", "ORDER_FILL_RECALC"])
def test_rsi_callback_rollback_does_not_double_advance_the_rma(version, phase):
    compiled = compile_source(source(rsi_body(version), version))
    runtime, cls = runtime_for(compiled)
    deferred = phase == "ORDER_FILL_RECALC"

    def callback(sequence, bar, close, *, final=True, initial=False):
        tx = runtime.begin(
            CallbackFrame(
                "HISTORICAL_EVAL" if initial else phase,
                sequence,
                bar_index=bar,
                realtime=not initial and phase == "REALTIME_TICK",
                final_tick=final,
                defer_bar_commit=deferred,
            ),
            values=BarValues(
                close, close + 1, close - 1, close, 0, bar * 60000, (bar + 1) * 60000 - 1
            ),
        )
        cls(tx).run()
        output = [from_portable(event.payload["series"]) for event in runtime.visuals.working[-3:]]
        tx.commit()
        if deferred and final:
            runtime.finalize_bar(bar)
        return output

    for index, close in enumerate([1, 2, 3]):
        callback(2 * index, index, close, initial=True)
    for sequence, close, final, expected in [
        (6, 5, False, (100, 100, 0)),
        (7, 2, False, (50, 50, 50)),
        (8, 2, True, (50, 50, 50)),
    ]:
        assert_numbers(callback(sequence, 3, close, final=final), expected)
    clean, _ = runtime_for(compiled)
    assert_numbers(advance(clean, cls, [1, 2, 3, 2]), [None] * 6 + [100, 100, 0, 50, 50, 50])
    # Compare the observable series after speculative calls as well as one more
    # committed sample; callback receipts intentionally have different sequences.
    assert_numbers(values(runtime), [None] * 6 + [100, 100, 0, 50, 50, 50])
    assert_numbers(callback(10, 4, 4), [250 / 3, 250 / 3, 50 / 3])


@pytest.mark.parametrize("version", range(1, 7))
def test_builtin_wrong_named_parameter_is_rejected_by_producer(version):
    exp = builtin("exp", version)
    wrong = "x" if version >= 5 else "number"
    with pytest.raises(ConsumerBundleError):
        compile_source(source(f"plot({exp}({wrong}=1))", version))


@pytest.mark.parametrize("version", [5, 6])
def test_rsi_dynamic_length_and_removed_ratio_are_rejected(version):
    for expression in ("ta.rsi(close,close)", "ta.rsi(close,2.0)"):
        with pytest.raises(ConsumerBundleError):
            compile_source(source(f"plot({expression})", version))


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_legacy_ratio_rsi_keeps_its_distinct_unsupported_binding(version):
    # The legacy ratio overload is a different formula, not the RMA kernel.
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_CALL_BINDING"):
        compile_source(source("plot(rsi(close,2.0))", version))
