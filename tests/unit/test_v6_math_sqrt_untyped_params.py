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
