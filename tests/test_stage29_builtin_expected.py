"""Stage 2.9 independent expected values for Stage-2-executable builtins.

Expected numbers are elementary arithmetic or documented Pine rules, not
snapshots of this runtime. Sources:

- https://www.tradingview.com/pine-script-docs/language/built-ins/
- https://www.tradingview.com/pine-script-docs/language/operators/
- https://www.tradingview.com/pine-script-docs/language/type-system/
- https://www.tradingview.com/pine-script-reference/v6/
"""

from __future__ import annotations

import math

import pytest
from pinelib import is_na
from pinelib.state.checkpoint import from_portable

from tests.test_rc6_input_metadata import run_source


def _src(body: str, version: int = 6) -> str:
    header = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{header}("s29")\n{body}\n'


def _trace(body: str, version: int = 6, closes=(1, 2, 3)):
    runtime, _, _ = run_source(_src(body, version), closes=closes)
    return [from_portable(event.payload["series"]) for event in runtime.visuals.committed]


def _math(name: str, version: int) -> str:
    return f"math.{name}" if version >= 5 else name


@pytest.mark.parametrize("version", range(1, 7))
def test_stage29_abs_sqrt_pow_are_elementary(version):
    abs_f, sqrt_f, pow_f = _math("abs", version), _math("sqrt", version), _math("pow", version)
    # abs(-close), sqrt(close*close), pow(2, close)
    body = f"plot({abs_f}(-close))\nplot({sqrt_f}(close*close))\nplot({pow_f}(2, close))"
    out = _trace(body, version, closes=(1, 2, 4))
    expected = []
    for close in (1, 2, 4):
        expected.extend([abs(-close), math.sqrt(close * close), 2**close])
    assert out == expected


@pytest.mark.parametrize("version", [5, 6])
def test_stage29_max_min_are_elementary(version):
    body = "plot(math.max(close, 2))\nplot(math.min(close, 2))"
    out = _trace(body, version, closes=(1, 3))
    assert out == [2, 1, 3, 2]


@pytest.mark.parametrize("version", range(1, 7))
def test_stage29_history_missing_is_na(version):
    body = "plot(close[1])\nplot(na(close[1]))"
    out = _trace(body, version, closes=(10, 20, 30))
    assert is_na(out[0]) and out[1] is True
    assert out[2:] == [10, False, 20, False]


@pytest.mark.parametrize("version", [5, 6])
def test_stage29_int_float_string_conversions(version):
    body = 'plot(int(3.9))\nplot(int(-3.9))\nplot(float(2)==2.0)\nplot(str.length("ab"))'
    out = _trace(body, version, closes=(1,))
    # int() truncates toward zero; str.length is the documented character count.
    assert out == [3, -3, True, 2]


@pytest.mark.parametrize("version", [5, 6])
def test_stage29_array_and_map_sizes(version):
    body = (
        "xs=array.new<int>(3, 7)\n"
        "array.set(xs, 1, 9)\n"
        "plot(array.size(xs))\n"
        "plot(array.get(xs, 0))\n"
        "plot(array.get(xs, 1))\n"
        "m=map.new<string,int>()\n"
        'map.put(m,"a",1)\n'
        'map.put(m,"b",2)\n'
        "plot(map.size(m))"
    )
    out = _trace(body, version, closes=(1,))
    assert out == [3, 7, 9, 2]


@pytest.mark.parametrize(
    "body,expected",
    [
        ("plot(nz(close[1], -1))", [-1.0, 1.0, 2.0]),
        ("plot(color.r(color.red))", [242.0, 242.0, 242.0]),
        ('plot(str.contains("abc","b"))', [True, True, True]),
    ],
)
def test_stage29_repaired_builtins_have_independent_expected(body, expected):
    # Replaces the old unsupported assumption, not the numerical oracle.
    assert _trace(body, 6) == expected


@pytest.mark.parametrize("version", [5, 6])
def test_stage29_sma_warmup_is_hand_derived_mean(version):
    # SMA(3) of 3,6,9,12: first two bars na, then (3+6+9)/3=6, (6+9+12)/3=9
    body = "plot(ta.sma(close, 3))"
    out = _trace(body, version, closes=(3, 6, 9, 12))
    assert is_na(out[0]) and is_na(out[1])
    assert out[2:] == [6.0, 9.0]
