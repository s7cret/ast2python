from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ast2python.ast.schema import load_ast
from ast2python.coverage import static_coverage_report
from ast2python.errors import UnsupportedBuiltinError
from ast2python.translator import translate_ast as _translate_ast
from tests.contract_metadata import with_valid_producer_metadata


def translate_ast(program, *args, **kwargs):
    return _translate_ast(with_valid_producer_metadata(program), *args, **kwargs)

PINE2AST = Path("[local-home]/pine2ast/tests/fixtures/golden_ast/valid")


@pytest.mark.parametrize(
    "relative, expected",
    [
        ("collections/generic_array.ast.json", {"array.new"}),
        ("collections/map_matrix_types.ast.json", {"map.new", "matrix.new"}),
        ("imports/import_alias_external_call.ast.json", {"lib.someFunction"}),
        ("optimizer_contract/strategy_exit.ast.json", {"strategy.entry", "strategy.exit"}),
        (
            "real_world_smoke/13_input_source_strategy_state.ast.json",
            {"input.source", "input.int", "ta.ema", "strategy.entry"},
        ),
    ],
)
def test_v0_7_real_pine2ast_fixtures_translate_and_compile(
    relative: str, expected: set[str]
) -> None:
    program = load_ast(PINE2AST / relative)
    static = static_coverage_report(program)
    assert static["schema_supported_ratio"] >= 0.98

    if relative.startswith("imports/"):
        with pytest.raises(UnsupportedBuiltinError):
            translate_ast(program, module_name=Path(relative).stem)
        result = translate_ast(
            program,
            module_name=Path(relative).stem,
            allow_external_library_stubs=True,
        )
        assert result.metadata["parity_safe"] is False
        assert "external_library_stubs" in result.metadata["unsupported_features"]
    else:
        result = translate_ast(program, module_name=Path(relative).stem)

    compile(result.code, relative, "exec")

    assert result.coverage["source_map_executable_line_ratio"] >= 0.95
    assert expected <= set(result.coverage["builtins"])
    assert result.metadata["generator_milestone"] == "v1.0.0"


def test_v0_7_unsupported_request_financial_is_diagnostic_not_placeholder_crash() -> None:
    program = load_ast(PINE2AST / "real_world_smoke/14_na_request_financial.ast.json")
    with pytest.raises(UnsupportedBuiltinError):
        translate_ast(program, module_name="request_financial")

    result = translate_ast(
        program,
        module_name="request_financial",
        allow_unsupported_request_stubs=True,
    )

    compile(result.code, "request_financial.py", "exec")
    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert "P2A_UNSUPPORTED_REQUEST" in codes
    assert "request.financial" in result.coverage["builtins"]
    assert result.metadata["parity_safe"] is False
    assert "unsupported_request_stub" in result.metadata["unsupported_features"]


def test_v0_7_supported_real_fixture_smoke_runs_or_skips_cleanly(tmp_path: Path) -> None:
    program = load_ast(PINE2AST / "real_world_smoke/01_ma_indicator.ast.json")
    result = translate_ast(program, module_name="real_world_ma")
    paths = result.write_to(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "ast2python.cli.main", "smoke", str(paths["python"])],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["runtime"] in {"executed", "skipped"}


def test_v0_7_alert_recorder_generation() -> None:
    program = {
        "kind": "Program",
        "language": "pine",
        "version": 6,
        "declaration": {
            "kind": "DeclarationStatement",
            "script_type": "indicator",
            "call": {
                "kind": "CallExpr",
                "callee": {"kind": "Identifier", "name": "indicator"},
                "arguments": [
                    {
                        "kind": "Argument",
                        "name": None,
                        "value": {"kind": "Literal", "literal_type": "string", "value": "alerts"},
                    }
                ],
            },
        },
        "items": [
            {
                "kind": "ExpressionStatement",
                "span": {"start_line": 3, "start_col": 1},
                "expression": {
                    "kind": "CallExpr",
                    "callee": {"kind": "Identifier", "name": "alert"},
                    "arguments": [
                        {
                            "kind": "Argument",
                            "name": None,
                            "value": {"kind": "Literal", "literal_type": "string", "value": "ping"},
                        }
                    ],
                },
            },
            {
                "kind": "ExpressionStatement",
                "span": {"start_line": 4, "start_col": 1},
                "expression": {
                    "kind": "CallExpr",
                    "callee": {"kind": "Identifier", "name": "alertcondition"},
                    "arguments": [
                        {
                            "kind": "Argument",
                            "name": None,
                            "value": {"kind": "Literal", "literal_type": "bool", "value": True},
                        },
                        {
                            "kind": "Argument",
                            "name": "title",
                            "value": {"kind": "Literal", "literal_type": "string", "value": "ok"},
                        },
                    ],
                },
            },
        ],
    }
    result = translate_ast(program, module_name="alerts")
    assert "self._record_alert('alert'" in result.code
    assert "self._record_alert('alertcondition'" in result.code
    compile(result.code, "alerts.py", "exec")
