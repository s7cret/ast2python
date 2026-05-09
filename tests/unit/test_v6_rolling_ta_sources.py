"""Tests for rolling TA call: Series source must be passed, not .current scalar."""
import pytest
import sys
sys.path.insert(0, "[local-home]/pine2ast")
from pine2ast.api import parse_code, runtime_contract_v1_4_options
from pine2ast.ast.serialize import ast_to_dict
from ast2python.translator import translate_ast


def get_generated_code(module_name: str, pine_code: str) -> str:
    """Translate and return the generated source code."""
    parsed = parse_code(pine_code, runtime_contract_v1_4_options(source_name="test.pine"))
    ast_dict = ast_to_dict(parsed.ast)
    result = translate_ast(ast_dict, module_name=module_name, allow_invalid_ast=True, allow_contract_mismatch=True)
    return result.code


class TestRollingTASources:
    """Verify rolling/window/history TA functions receive Series, not .current scalar."""

    def test_highest_lowest_source_is_series(self):
        code = """//@version=6
indicator("test")
h = ta.highest(high, 20)
l = ta.lowest(low, 20)
plot(h, "H")
plot(l, "L")"""
        src = get_generated_code("test_hl", code)
        assert "highest(self.rt.high," in src, f"highest missing Series arg"
        assert "lowest(self.rt.low," in src, f"lowest missing Series arg"
        assert "highest(self.rt.high.current," not in src, "highest got scalar .current!"
        assert "lowest(self.rt.low.current," not in src, "lowest got scalar .current!"

    def test_stdev_source_is_series(self):
        code = """//@version=6
indicator("test")
basis = ta.sma(close, 20)
dev = ta.stdev(close, 20)
upper = basis + 2.0 * dev
plot(upper, "UPPER")"""
        src = get_generated_code("test_stdev", code)
        assert "stdev(self.rt.close," in src, f"stdev missing Series arg"
        assert "stdev(self.rt.close.current," not in src, "stdev got scalar .current!"

    def test_variance_source_is_series(self):
        code = """//@version=6
indicator("test")
v = ta.variance(close, 20)
plot(v, "VAR")"""
        src = get_generated_code("test_var", code)
        assert "variance(self.rt.close," in src, f"variance missing Series arg"
        assert "variance(self.rt.close.current," not in src, "variance got scalar .current!"

    def test_dev_source_is_series(self):
        code = """//@version=6
indicator("test")
d = ta.dev(close, 20)
plot(d, "DEV")"""
        src = get_generated_code("test_dev", code)
        assert "dev(self.rt.close," in src, f"dev missing Series arg"
        assert "dev(self.rt.close.current," not in src, "dev got scalar .current!"

    def test_change_source_is_series(self):
        code = """//@version=6
indicator("test")
x = ta.change(close)
plot(x, "CHANGE")"""
        src = get_generated_code("test_change", code)
        # check for change call with Series close
        assert ("change(self.rt.close," in src or "change(self.rt.close)" in src), \
            f"change missing Series arg"
        assert "change(self.rt.close.current," not in src, "change got scalar .current!"

    def test_ichimoku_sources_are_series(self):
        code = """//@version=6
indicator("test")
tenkan = (ta.highest(high, 9) + ta.lowest(low, 9)) / 2.0
kijun = (ta.highest(high, 26) + ta.lowest(low, 26)) / 2.0
plot(tenkan, "TENKAN")
plot(kijun, "KIJUN")"""
        src = get_generated_code("test_ichi", code)
        assert "highest(self.rt.high," in src, f"highest(high) missing Series"
        assert "lowest(self.rt.low," in src, f"lowest(low) missing Series"
        assert "highest(self.rt.high.current," not in src, "highest got scalar!"
        assert "lowest(self.rt.low.current," not in src, "lowest got scalar!"

    def test_ta_range_source_is_series(self):
        code = """//@version=6
indicator("test")
x = ta.range(close, 20)
plot(x, "RANGE")"""
        src = get_generated_code("test_range", code)
        # ta.range maps to ta_range in pinelib
        assert "ta_range(self.rt.close," in src, f"ta_range missing Series arg"
        assert "ta_range(self.rt.close.current," not in src, "ta_range got scalar .current!"

    def test_bb_stdev_uses_series(self):
        code = """//@version=6
indicator("test")
basis = ta.sma(close, 20)
bbDev = ta.stdev(close, 20) * 2.0
bbUpper = basis + bbDev
bbLower = basis - bbDev
plot(bbUpper, "UPPER")"""
        src = get_generated_code("test_bb", code)
        assert "stdev(self.rt.close," in src, f"BB stdev missing Series"
        assert "stdev(self.rt.close.current," not in src, "BB stdev got scalar!"

    def test_pivothigh_low_source_is_series(self):
        code = """//@version=6
indicator("test")
ph = ta.pivothigh(high, 3, 3)
pl = ta.pivotlow(low, 3, 3)
plot(ph, "PH")
plot(pl, "PL")"""
        src = get_generated_code("test_pivot", code)
        assert "pivothigh(self.rt.high," in src, f"pivothigh missing Series"
        assert "pivothigh(self.rt.high.current," not in src, "pivothigh got scalar!"
        assert "pivotlow(self.rt.low," in src, f"pivotlow missing Series"
        assert "pivotlow(self.rt.low.current," not in src, "pivotlow got scalar!"

    def test_rising_falling_source_is_series(self):
        code = """//@version=6
indicator("test")
r = ta.rising(close, 2)
f = ta.falling(close, 2)
plot(r ? 1 : 0, "RISE")
plot(f ? 1 : 0, "FALL")"""
        src = get_generated_code("test_rf", code)
        assert "rising(self.rt.close," in src, f"rising missing Series"
        assert "rising(self.rt.close.current," not in src, "rising got scalar!"
        assert "falling(self.rt.close," in src, f"falling missing Series"
        assert "falling(self.rt.close.current," not in src, "falling got scalar!"

    def test_correlation_sources_are_series(self):
        code = """//@version=6
indicator("test")
x = ta.correlation(close, volume, 20)
plot(x, "CORR")"""
        src = get_generated_code("test_corr", code)
        # correlation(self.rt.close, self.rt.volume, 20) — both sources as Series
        assert "self.rt.close, self.rt.volume" in src, f"correlation missing both Series args"
        assert "self.rt.close.current," not in src, "correlation got scalar for source1!"
        assert "self.rt.volume.current," not in src, "correlation got scalar for source2!"
