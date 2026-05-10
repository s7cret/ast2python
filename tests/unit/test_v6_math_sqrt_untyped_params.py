from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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


def _translate_ast(tmp_path: Path, ast_path: Path, module_name: str) -> subprocess.CompletedProcess[str]:
    return _run(
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
            "--allow-invalid-ast",
        ]
    )


def test_v6_hma_untyped_length_binds_sqrt_and_ta_wma(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "hma_untyped",
        """
        //@version=6
        indicator("test")
        hma(src, length) =>
            half = math.max(1, int(math.round(length / 2.0)))
            sqrtLen = math.max(1, int(math.round(math.sqrt(length))))
            ta.wma(2.0 * ta.wma(src, half) - ta.wma(src, length), sqrtLen)
        plot(hma(close, 20))
        """,
    )

    translate = _translate_ast(tmp_path, ast_path, "hma_untyped")
    assert translate.returncode == 0, translate.stderr + translate.stdout
    payload = json.loads(translate.stdout)
    py_path = Path(payload["paths"]["python"])
    meta_path = Path(payload["paths"]["metadata"])

    code = py_path.read_text(encoding="utf-8")
    compile(code, str(py_path), "exec")
    assert "sqrt(length)" in code
    assert "wma(src, half)" in code
    assert "wma(src, length)" in code
    assert "wma(pine_sub" in code and "sqrt_len" in code

    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["types"]["function_1:sqrtLen"]["base_type"] == "int"
    assert metadata["types"]["function_1:sqrtLen"]["qualifier"] == "simple"
    assert metadata["types"]["function_1:half"]["base_type"] == "int"
    assert metadata["types"]["function_1:half"]["qualifier"] == "simple"


def test_v6_math_sqrt_rejects_explicit_string_literal(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "bad_sqrt_string",
        """
        //@version=6
        indicator("bad")
        x = math.sqrt("abc")
        plot(x)
        """,
    )

    translate = _translate_ast(tmp_path, ast_path, "bad_sqrt_string")
    assert translate.returncode != 0
    assert "math.sqrt semantic binding failed" in translate.stderr


def test_v6_supertrend_lowers_to_runtime_ohlc_tuple(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "supertrend_runtime",
        """
        //@version=6
        indicator("supertrend test")
        [st, dir] = ta.supertrend(3.0, 10)
        plot(st, "ST")
        plot(dir, "DIR")
        """,
    )

    translate = _translate_ast(tmp_path, ast_path, "supertrend_runtime")
    assert translate.returncode == 0, translate.stderr + translate.stdout
    payload = json.loads(translate.stdout)
    py_path = Path(payload["paths"]["python"])
    meta_path = Path(payload["paths"]["metadata"])

    code = py_path.read_text(encoding="utf-8")
    compile(code, str(py_path), "exec")
    assert 'from pinelib.ta import supertrend' in code
    assert 'supertrend(3.0, 10, runtime=self.rt, state_id=' in code
    assert "_st, _dir_ = supertrend(" in code
    assert "self.st.set_current(_st)" in code
    assert "self.dir_.set_current(_dir_)" in code

    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["types"]["global:st"]["base_type"] == "float"
    assert metadata["types"]["global:dir"]["base_type"] == "int"

    spec = importlib.util.spec_from_file_location("supertrend_runtime", py_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["supertrend_runtime"] = module
    spec.loader.exec_module(module)

    from pinelib.core import Bar, PineRuntime, SymbolInfo, TimeframeInfo

    runtime = PineRuntime(
        symbol_info=SymbolInfo("BINANCE:BTCUSDT", mintick=0.01),
        timeframe=TimeframeInfo.from_string("15"),
    )
    script = module.GeneratedIndicator(runtime=runtime)
    script.run(
        [
            Bar(time=0, time_close=899_999, open=100, high=105, low=99, close=101, volume=10),
            Bar(time=900_000, time_close=1_799_999, open=101, high=106, low=100, close=104, volume=11),
        ]
    )


def test_v6_dmi_and_sar_lower_to_runtime_ohlc_inputs(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "dmi_sar_runtime",
        """
        //@version=6
        indicator("dmi sar test")
        [plus, minus, adx] = ta.dmi(14, 14)
        sar = ta.sar(0.02, 0.02, 0.2)
        plot(plus, "PLUS")
        plot(minus, "MINUS")
        plot(adx, "ADX")
        plot(sar, "SAR")
        """,
    )

    translate = _translate_ast(tmp_path, ast_path, "dmi_sar_runtime")
    assert translate.returncode == 0, translate.stderr + translate.stdout
    payload = json.loads(translate.stdout)
    py_path = Path(payload["paths"]["python"])

    code = py_path.read_text(encoding="utf-8")
    compile(code, str(py_path), "exec")
    assert 'from pinelib.ta import dmi, sar' in code
    assert 'dmi(self.rt.high.current, self.rt.low.current, self.rt.close.current, 14, 14' in code
    assert 'sar(self.rt.high.current, self.rt.low.current, 0.02, 0.02, 0.2' in code
    assert "_plus, _minus, _adx = dmi(" in code


def test_v6_ta_tr_lowers_to_runtime_ohlc(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "tr_runtime",
        """
        //@version=6
        indicator("tr test")
        plot(ta.tr(true), "TR")
        """,
    )

    translate = _translate_ast(tmp_path, ast_path, "tr_runtime")
    assert translate.returncode == 0, translate.stderr + translate.stdout
    payload = json.loads(translate.stdout)
    py_path = Path(payload["paths"]["python"])

    code = py_path.read_text(encoding="utf-8")
    compile(code, str(py_path), "exec")
    assert 'from pinelib.ta import tr' in code
    assert 'tr(runtime=self.rt, state_id=' in code


def test_v6_ta_range_preserves_builtin_series_source(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "ta_range_series_source",
        """
        //@version=6
        indicator("ta range source test")
        len = input.int(20)
        x = ta.range(close, len)
        plot(x, "RANGE")
        """,
    )

    translate = _translate_ast(tmp_path, ast_path, "ta_range_series_source")
    assert translate.returncode == 0, translate.stderr + translate.stdout
    payload = json.loads(translate.stdout)
    py_path = Path(payload["paths"]["python"])

    code = py_path.read_text(encoding="utf-8")
    compile(code, str(py_path), "exec")
    assert 'from pinelib.ta import ta_range' in code
    assert 'ta_range(self.rt.close, self.len_.current, runtime=self.rt, state_id=' in code
    assert 'ta_range(self.rt.close.current' not in code

    spec = importlib.util.spec_from_file_location("ta_range_series_source", py_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ta_range_series_source"] = module
    spec.loader.exec_module(module)

    from pinelib.core import Bar, PineRuntime, SymbolInfo, TimeframeInfo

    runtime = PineRuntime(
        symbol_info=SymbolInfo("BINANCE:BTCUSDT", mintick=0.01),
        timeframe=TimeframeInfo.from_string("15"),
    )
    script = module.GeneratedIndicator(runtime=runtime)
    bars = [
        Bar(
            time=index * 900_000,
            time_close=(index + 1) * 900_000 - 1,
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            volume=10 + index,
        )
        for index in range(299)
    ]
    script.run(bars)


def test_v6_ta_range_nested_in_math_preserves_series_source(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "ta_range_nested_math",
        """
        //@version=6
        indicator("ta range in math")
        x = math.max(ta.range(close, 20), 0)
        plot(x, "RANGE_MAX")
        """,
    )

    translate = _translate_ast(tmp_path, ast_path, "ta_range_nested_math")
    assert translate.returncode == 0, translate.stderr + translate.stdout
    payload = json.loads(translate.stdout)
    py_path = Path(payload["paths"]["python"])

    code = py_path.read_text(encoding="utf-8")
    compile(code, str(py_path), "exec")
    assert 'from pinelib.ta import ta_range' in code
    assert 'pine_max(ta_range(self.rt.close, 20, runtime=self.rt, state_id=' in code
    assert 'ta_range(self.rt.close.current' not in code


def test_v6_ta_sma_accepts_untyped_function_params(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "sma_untyped_params",
        """
        //@version=6
        indicator("sma untyped params")
        f(src, length) => ta.sma(src, length)
        plot(f(close, 20))
        """,
    )

    translate = _translate_ast(tmp_path, ast_path, "sma_untyped_params")
    assert translate.returncode == 0, translate.stderr + translate.stdout
    payload = json.loads(translate.stdout)
    py_path = Path(payload["paths"]["python"])

    code = py_path.read_text(encoding="utf-8")
    compile(code, str(py_path), "exec")
    assert 'from pinelib.ta import sma' in code
    assert 'sma(src, length, runtime=self.rt, state_id=' in code


def test_v6_ta_sma_accepts_derived_builtin_series_source(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "sma_hl2",
        """
        //@version=6
        indicator("sma hl2")
        x = ta.sma(hl2, 5)
        plot(x)
        """,
    )

    translate = _translate_ast(tmp_path, ast_path, "sma_hl2")
    assert translate.returncode == 0, translate.stderr + translate.stdout
    payload = json.loads(translate.stdout)
    py_path = Path(payload["paths"]["python"])

    code = py_path.read_text(encoding="utf-8")
    compile(code, str(py_path), "exec")
    # hl2 is a DERIVED_BUILTIN_SERIES used as SMA source → hl2_series must be imported
    assert 'from pinelib.ta import' in code and 'sma' in code and 'hl2_series' in code
    # hl2 should use _RuntimeDerivedSeries for proper runtime semantics
    assert 'hl2_series(self.rt)' in code


def test_v6_crossover_accepts_nested_ta_numeric_source(tmp_path: Path) -> None:
    ast_path = _parse_pine(
        tmp_path,
        "crossover_cci",
        """
        //@version=6
        indicator("crossover cci")
        sig = ta.crossover(ta.cci(hlc3, 20), 0)
        plot(sig ? 1 : 0)
        """,
    )

    translate = _translate_ast(tmp_path, ast_path, "crossover_cci")
    assert translate.returncode == 0, translate.stderr + translate.stdout
    payload = json.loads(translate.stdout)
    py_path = Path(payload["paths"]["python"])

    code = py_path.read_text(encoding="utf-8")
    compile(code, str(py_path), "exec")
    assert 'from pinelib.ta import cci, crossover' in code
    assert 'crossover(cci(' in code
