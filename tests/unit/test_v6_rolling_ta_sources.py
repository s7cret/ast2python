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

    def test_wma_source_is_series_no_runtime(self):
        """WMA: source=Series (batch mode, no runtime= needed).

        WMA is NOT in STATEFUL_TA_FUNCTIONS (intentionally, to preserve user-defined
        function inlining for hma pattern). WMA works in batch mode — pinelib wma
        receives the full Series and computes all values without needing runtime=/state_id=.
        """
        code = """//@version=6
indicator("test")
plot(ta.wma(close, 20), "WMA")"""
        src = get_generated_code("test_wma", code)
        # source must be Series (no .current) — this is the key fix
        assert "wma(self.rt.close," in src, f"wma missing Series source"
        assert "wma(self.rt.close.current," not in src, "wma got scalar .current!"
        # WMA uses batch mode — no runtime=/state_id=
        assert "runtime=self.rt" not in src, "wma should NOT have runtime= (batch mode)"

    def test_swma_source_is_series_no_runtime(self):
        """SWMA: source=Series, NO runtime=/state_id= (pinelib swma has no runtime support)."""
        code = """//@version=6
indicator("test")
plot(ta.swma(close), "SWMA")"""
        src = get_generated_code("test_swma", code)
        # source must be Series (no .current)
        assert "swma(self.rt.close" in src, f"swma missing Series source"
        assert "swma(self.rt.close.current" not in src, "swma got scalar .current!"
        # must NOT have runtime= (swma pinelib doesn't support it)
        assert "runtime=self.rt" not in src, "swma should NOT have runtime= argument"

    def test_vwma_source_is_series_with_runtime(self):
        """VWMA: source=Series (no .current), has runtime= and state_id=."""
        code = """//@version=6
indicator("test")
plot(ta.vwma(close, 20), "VWMA")"""
        src = get_generated_code("test_vwma", code)
        assert "vwma(self.rt.close," in src, f"vwma missing Series source"
        assert "vwma(self.rt.close.current," not in src, "vwma got scalar .current!"
        assert "runtime=self.rt" in src, "vwma missing runtime= argument"
        assert 'state_id="' in src, "vwma missing state_id= argument"

    def test_stoch_all_sources_are_series(self):
        """STOCH: source/high/low all as Series (no .current), has runtime= and state_id=."""
        code = """//@version=6
indicator("test")
plot(ta.stoch(close, high, low, 14), "STOCH")"""
        src = get_generated_code("test_stoch", code)
        # all three sources must be Series
        assert "stoch(self.rt.close," in src, f"stoch missing close source"
        assert "self.rt.close.current," not in src, "stoch close got .current!"
        assert "self.rt.high," in src, f"stoch missing high source"
        assert "self.rt.high.current," not in src, "stoch high got .current!"
        assert "self.rt.low," in src, f"stoch missing low source"
        assert "self.rt.low.current," not in src, "stoch low got .current!"
        assert "runtime=self.rt" in src, "stoch missing runtime= argument"
        assert 'state_id="' in src, "stoch missing state_id= argument"

    def test_mom_source_is_series_with_runtime(self):
        """MOM: source=Series, has runtime= and state_id=."""
        code = """//@version=6
indicator("test")
plot(ta.mom(close, 10), "MOM")"""
        src = get_generated_code("test_mom", code)
        assert "mom(self.rt.close," in src, f"mom missing Series source"
        assert "mom(self.rt.close.current," not in src, "mom got scalar .current!"
        assert "runtime=self.rt" in src, "mom missing runtime= argument"
        assert 'state_id="' in src, "mom missing state_id= argument"

    def test_roc_source_is_series_with_runtime(self):
        """ROC: source=Series, has runtime= and state_id=."""
        code = """//@version=6
indicator("test")
plot(ta.roc(close, 10), "ROC")"""
        src = get_generated_code("test_roc", code)
        assert "roc(self.rt.close," in src, f"roc missing Series source"
        assert "roc(self.rt.close.current," not in src, "roc got scalar .current!"
        assert "runtime=self.rt" in src, "roc missing runtime= argument"
        assert 'state_id="' in src, "roc missing state_id= argument"

    def test_mfi_source_is_series_with_runtime(self):
        """MFI: source=Series, has runtime= and state_id=."""
        code = """//@version=6
indicator("test")
plot(ta.mfi(close, 14), "MFI")"""
        src = get_generated_code("test_mfi", code)
        assert "mfi(self.rt.close," in src, f"mfi missing Series source"
        assert "mfi(self.rt.close.current," not in src, "mfi got scalar .current!"
        assert "runtime=self.rt" in src, "mfi missing runtime= argument"
        assert 'state_id="' in src, "mfi missing state_id= argument"

    def test_vwap_source_uses_runtime_volume(self):
        """VWAP: source (hlc3) via runtime, volume from runtime.volume, has runtime=."""
        code = """//@version=6
indicator("test")
plot(ta.vwap(hlc3), "VWAP")"""
        src = get_generated_code("test_vwap", code)
        # vwap must have runtime= (volume sourced from runtime.volume)
        assert "runtime=self.rt" in src, "vwap missing runtime= argument"
        assert 'state_id="' in src, "vwap missing state_id= argument"



    def test_alma_source_is_series_no_runtime(self):
        """ALMA: source=Series, NO runtime= (batch mode works; alma NOT in STATEFUL_TA_FUNCTIONS)."""
        code = """//@version=6
indicator("test")
plot(ta.alma(close, 20, 0.85, 6), "ALMA")"""
        src = get_generated_code("test_alma", code)
        assert "alma(self.rt.close," in src, f"alma missing Series source"
        assert "alma(self.rt.close.current," not in src, "alma got scalar .current!"
        assert "runtime=self.rt" not in src, "alma should NOT have runtime= (batch mode)"

    def test_linreg_source_is_series_no_runtime(self):
        """LINREG: source=Series, NO runtime= (batch mode works; linreg NOT in STATEFUL_TA_FUNCTIONS)."""
        code = """//@version=6
indicator("test")
plot(ta.linreg(close, 20, 0), "LINREG")"""
        src = get_generated_code("test_linreg", code)
        assert "linreg(self.rt.close," in src, f"linreg missing Series source"
        assert "linreg(self.rt.close.current," not in src, "linreg got scalar .current!"
        assert "runtime=self.rt" not in src, "linreg should NOT have runtime= (batch mode)"

    def test_cci_source_is_series_with_runtime(self):
        """CCI: source=Series, has runtime= and state_id= (in STATEFUL_TA_FUNCTIONS)."""
        code = """//@version=6
indicator("test")
plot(ta.cci(hlc3, 20), "CCI")"""
        src = get_generated_code("test_cci", code)
        # hlc3 maps to a Series; cci gets runtime=/state_id=
        assert "cci(" in src, f"cci call missing"
        assert "runtime=self.rt" in src, "cci missing runtime= argument"
        assert 'state_id="' in src, "cci missing state_id= argument"
