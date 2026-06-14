from __future__ import annotations

import importlib.util
import json
import os
import pytest
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


sys.path.insert(0, str(ROOT.parent / "pinelib"))
from pinelib.core import Bar, PineRuntime, SymbolInfo, TimeframeInfo  # noqa: E402


def _env() -> dict[str, str]:
    paths = [
        str(ROOT),
        str(ROOT.parent / "pine2ast"),
        str(ROOT.parent / "pinelib"),
    ]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    return os.environ | {"PYTHONPATH": os.pathsep.join(paths)}


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        env=_env(),
        text=True,
        capture_output=True,
        check=False,
    )


def _parse_pine(tmp_path: Path, name: str, source: str) -> Path:
    pine_path = tmp_path / f"{name}.pine"
    ast_path = tmp_path / f"{name}.ast.json"
    pine_path.write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")
    parse = _run(
        [
            sys.executable,
            "-m",
            "pine2ast",
            "parse",
            str(pine_path),
            "--json",
            str(ast_path),
            "--runtime-contract-v1-4",
        ]
    )
    assert parse.returncode == 0, parse.stderr + parse.stdout
    assert ast_path.exists()
    return ast_path


def _translate_ast(tmp_path: Path, ast_path: Path, module_name: str) -> Path:
    translate = _run(
        [
            sys.executable,
            "-m",
            "ast2python.cli.main",
            "translate",
            str(ast_path),
            "-o",
            str(tmp_path / "generated"),
            "--module-name",
            module_name,
            "--compile-profile",
            "diagnostic",
            "--allow-invalid-ast",
        ]
    )
    assert translate.returncode == 0, translate.stderr + translate.stdout
    payload = json.loads(translate.stdout)
    return Path(payload["paths"]["python"])


def _load_generated(py_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, py_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _runtime() -> PineRuntime:
    return PineRuntime(
        SymbolInfo(tickerid="AAPL", timezone="UTC", session="0000-2359"),
        TimeframeInfo.from_string("1"),
    )


def _bars() -> list[Bar]:
    return [
        Bar(time=0, time_close=59_999, open=10, high=11, low=9, close=10, volume=100),
        Bar(time=60_000, time_close=119_999, open=20, high=21, low=19, close=20, volume=200),
    ]


def test_v6_modulo_operator_generates_valid_python(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "modulo_test",
        """
        //@version=6
        indicator("modulo test")
        x = bar_index % 2
        plot(x, "MOD")
        """,
    )

    py_path = _translate_ast(tmp_path, ast_path, "modulo_test")
    code = py_path.read_text(encoding="utf-8")

    compile(code, str(py_path), "exec")
    assert "self.rt.bar_index_series.current % 2" in code


def test_v6_modulo_operator_in_bool_expressions(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "modulo_bool_test",
        """
        //@version=6
        indicator("modulo bool test")
        debugFlipBars = input.int(10)
        sigLong = bar_index % debugFlipBars == 0
        sigShort = bar_index % debugFlipBars == math.floor(debugFlipBars / 2)
        plot(sigLong ? 1 : 0, "LONG")
        plot(sigShort ? 1 : 0, "SHORT")
        """,
    )

    py_path = _translate_ast(tmp_path, ast_path, "modulo_bool_test")
    code = py_path.read_text(encoding="utf-8")

    compile(code, str(py_path), "exec")
    assert "self.rt.bar_index_series.current % self.debug_flip_bars.current" in code
    assert "pine_eq((self.rt.bar_index_series.current % self.debug_flip_bars.current), 0)" in code
    assert (
        "pine_eq((self.rt.bar_index_series.current % self.debug_flip_bars.current), "
        "floor(pine_div(self.debug_flip_bars.current, 2)))" in code
    )


def test_v6_strategy_close_accepts_named_comment(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "strategy_close_comment_test",
        """
        //@version=6
        strategy("strategy close comment test")
        if bar_index % 2 == 0
            strategy.entry("L", strategy.long)
        else
            strategy.close("L", comment="close long")
        """,
    )

    py_path = _translate_ast(tmp_path, ast_path, "strategy_close_comment_test")
    code = py_path.read_text(encoding="utf-8")

    compile(code, str(py_path), "exec")
    assert "self.ctx.close('L', comment='close long'" in code


def test_v6_strategy_entry_accepts_dynamic_named_comment(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "strategy_entry_comment_test",
        """
        //@version=6
        strategy("strategy entry comment test")
        engine = input.string("X")
        if bar_index % 2 == 0
            strategy.entry("L", strategy.long, comment="P4_LONG_" + engine)
        else
            strategy.entry("S", strategy.short, comment="P4_SHORT_" + engine)
        """,
    )

    py_path = _translate_ast(tmp_path, ast_path, "strategy_entry_comment_test")
    code = py_path.read_text(encoding="utf-8")

    compile(code, str(py_path), "exec")
    assert "self.ctx.entry('L', \"long\", comment=pine_add('P4_LONG_', self.engine.current)" in code
    assert (
        "self.ctx.entry('S', \"short\", comment=pine_add('P4_SHORT_', self.engine.current)" in code
    )


def test_v6_switch_signal_uses_case_body_values_and_executes(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "switch_signal_test",
        """
        //@version=6
        strategy("switch signal test")
        engine = input.string("Debug", options=["SuperTrend", "Debug"])
        sigDebugLong = bar_index % 2 == 0
        sigStLong = close > open
        longSignal = switch engine
            "SuperTrend" => sigStLong
            "Debug" => sigDebugLong
        if longSignal
            strategy.entry("L", strategy.long)
        """,
    )

    py_path = _translate_ast(tmp_path, ast_path, "switch_signal_test")
    code = py_path.read_text(encoding="utf-8")

    compile(code, str(py_path), "exec")
    assert "self.long_signal.set_current(" in code
    assert "self.sig_st_long.current if self.engine.current == 'SuperTrend'" in code
    assert "self.sig_debug_long.current if self.engine.current == 'Debug'" in code
    assert "na if self.engine.current == 'SuperTrend'" not in code

    module = _load_generated(py_path, "switch_signal_test")
    runtime = _runtime()
    module.GeneratedStrategy(runtime=runtime).run(_bars())
    assert runtime.series_registry["long_signal"]._history == [True, False]


def test_v6_switch_default_branch_returns_default_value(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "switch_default_test",
        """
        //@version=6
        indicator("switch default test")
        engine = input.string("X")
        x = switch engine
            "A" => 1
            "B" => 2
            => 3
        plot(x)
        """,
    )

    py_path = _translate_ast(tmp_path, ast_path, "switch_default_test")
    code = py_path.read_text(encoding="utf-8")

    compile(code, str(py_path), "exec")
    assert "self.x.set_current((1 if self.engine.current == 'A' else" in code
    assert "2 if self.engine.current == 'B' else 3" in code

    module = _load_generated(py_path, "switch_default_test")
    runtime = _runtime()
    module.GeneratedIndicator(runtime=runtime).run(_bars())
    assert runtime.series_registry["x"]._history == [3, 3]


def test_v6_request_security_daily_close_compile_shape(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "security_close_d",
        """
        //@version=6
        indicator("security close D")
        x = request.security(syminfo.tickerid, "D", close, gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_off)
        plot(x, "D_CLOSE")
        """,
    )

    py_path = _translate_ast(tmp_path, ast_path, "security_close_d")
    code = py_path.read_text(encoding="utf-8")

    compile(code, str(py_path), "exec")
    assert "request_security(self.rt.syminfo.tickerid, 'D'" in code
    assert "lambda request_rt: request_rt.close.current" in code
    assert "gaps='barmerge.gaps_off'" in code
    assert "lookahead='barmerge.lookahead_off'" in code


def test_v6_request_security_daily_previous_close_compile_shape(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "security_close_prev_d",
        """
        //@version=6
        indicator("security close prev D")
        x = request.security(syminfo.tickerid, "D", close[1], gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_off)
        plot(x, "D_PREV_CLOSE")
        """,
    )

    py_path = _translate_ast(tmp_path, ast_path, "security_close_prev_d")
    code = py_path.read_text(encoding="utf-8")

    compile(code, str(py_path), "exec")
    assert "request_security(self.rt.syminfo.tickerid, 'D'" in code
    assert "lambda request_rt: request_rt.close[1]" in code
    assert "gaps='barmerge.gaps_off'" in code
    assert "lookahead='barmerge.lookahead_off'" in code


@pytest.mark.xfail(reason="time / time_close codegen handler not yet ported in 4.0")
def test_v6_daily_time_and_time_close_compile_shape(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "time_d",
        """
        //@version=6
        indicator("time D")
        plot(float(time("D")), "D_TIME")
        plot(float(time_close("D")), "D_TIME_CLOSE")
        """,
    )

    py_path = _translate_ast(tmp_path, ast_path, "time_d")
    code = py_path.read_text(encoding="utf-8")

    compile(code, str(py_path), "exec")
    assert "float(self.rt.timefunc.time('D', runtime=self.rt))" in code
    assert "float(self.rt.timefunc.time_close('D', runtime=self.rt))" in code
