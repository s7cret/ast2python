from __future__ import annotations

import json
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
            "--allow-invalid-ast",
        ]
    )
    assert translate.returncode == 0, translate.stderr + translate.stdout
    payload = json.loads(translate.stdout)
    return Path(payload["paths"]["python"])


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
