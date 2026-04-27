import json
import subprocess
import sys
from pathlib import Path

from ast2python.ast.schema import load_ast
from ast2python.translator import translate_ast

ROOT = Path(__file__).resolve().parents[2]
PINE2AST_FIXTURES = ROOT / "tests" / "fixtures" / "pine2ast"
EXPECTED = ROOT / "tests" / "fixtures" / "expected" / "v0_6"


def test_current_pine2ast_program_fixture_matches_generated_snapshot():
    fixture = PINE2AST_FIXTURES / "current_basic_indicator.ast.json"
    result = translate_ast(json.loads(fixture.read_text(encoding="utf-8")), module_name="current_basic_indicator")
    assert result.code == (EXPECTED / "current_basic_indicator.py").read_text(encoding="utf-8")
    assert result.metadata["generator_milestone"] == "v0.6.0"
    assert result.metadata["unsupported_nodes"] == []
    assert result.coverage["source_map_executable_line_ratio"] >= 0.95


def test_pine2ast_inspect_envelope_unwraps_for_cli_translate(tmp_path):
    fixture = PINE2AST_FIXTURES / "current_basic_indicator.envelope.json"
    program = load_ast(fixture)
    assert program.kind == "Program"

    out = tmp_path / "generated"
    proc = subprocess.run(
        [sys.executable, "-m", "ast2python.cli.main", "translate", str(fixture), "-o", str(out), "--module-name", "p2a_env"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    generated = Path(payload["paths"]["python"])
    assert generated.exists()

    smoke = subprocess.run(
        [sys.executable, "-m", "ast2python.cli.main", "smoke", str(generated)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert smoke.returncode == 0, smoke.stderr
    smoke_payload = json.loads(smoke.stdout)
    assert smoke_payload["runtime"] in {"executed", "skipped"}


def test_cli_coverage_includes_schema_catalog():
    fixture = PINE2AST_FIXTURES / "current_basic_indicator.ast.json"
    proc = subprocess.run(
        [sys.executable, "-m", "ast2python.cli.main", "coverage", str(fixture)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_supported_ratio"] == 1.0
    assert payload["node_kind_counts"]["Program"] == 1
    assert payload["unsupported_nodes"] == []
