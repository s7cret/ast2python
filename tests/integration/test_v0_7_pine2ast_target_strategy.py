from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ast2python.ast.schema import load_ast
from ast2python.coverage import static_coverage_report
from ast2python.errors import UnsupportedBuiltinError
from ast2python.translator import translate_ast as _translate_ast
from ast2python.version import __version__
from tests.contract_metadata import with_valid_producer_metadata


def translate_ast(program, *args, **kwargs):
    return _translate_ast(with_valid_producer_metadata(program), *args, **kwargs)


def parse_pine(source: str) -> dict:
    pytest.importorskip("pine2ast")
    from pine2ast.api import ParseOptions, parse_code

    result = parse_code(source, ParseOptions(run_semantic=True))
    errors = [diag for diag in result.diagnostics if diag.severity.value in {"ERROR", "FATAL"}]
    assert errors == []
    return result.ast.to_dict()


STACK_ROOT = Path(os.environ.get("PINE_STACK_ROOT", Path(__file__).resolve().parents[3]))
PINE2AST = STACK_ROOT / "pine2ast/tests/fixtures/golden_ast/valid"


def require_pine2ast_fixtures() -> None:
    if not PINE2AST.exists():
        pytest.skip("pine2ast golden fixtures are not available in this checkout")


@pytest.mark.parametrize(
    "relative, expected",
    [
        ("collections/generic_array.ast.json", {"array.new"}),
        ("collections/map_matrix_types.ast.json", {"map.new", "matrix.new"}),
        ("imports/import_alias_external_call.ast.json", {"lib.someFunction"}),
        ("optimizer_contract/strategy_exit.ast.json", {"strategy.entry", "strategy.exit"}),
        (
            "real_world_smoke/13_input_source_strategy_state.ast.json",
            {"input.int", "ta.ema", "strategy.entry"},
        ),
    ],
)
def test_v0_7_real_pine2ast_fixtures_translate_and_compile(
    relative: str, expected: set[str]
) -> None:
    require_pine2ast_fixtures()
    program = load_ast(PINE2AST / relative)
    static = static_coverage_report(program)
    assert static["schema_supported_ratio"] >= 0.98

    if relative.startswith("imports/"):
        with pytest.raises(UnsupportedBuiltinError):
            translate_ast(program, module_name=Path(relative).stem)
        result = translate_ast(
            program,
            module_name=Path(relative).stem,
            compile_profile="diagnostic",
            allow_external_library_stubs=True,
        )
        assert result.metadata["parity_safe"] is False
        assert "external_library_stubs" in result.metadata["unsupported_features"]
    else:
        result = translate_ast(program, module_name=Path(relative).stem)

    compile(result.code, relative, "exec")

    assert result.coverage["source_map_executable_line_ratio"] >= 0.95
    assert expected <= set(result.coverage["builtins"])
    assert result.metadata["generator_milestone"] == f"v{__version__}"


def test_v0_7_unsupported_request_financial_is_diagnostic_not_placeholder_crash() -> None:
    require_pine2ast_fixtures()
    program = load_ast(PINE2AST / "real_world_smoke/14_na_request_financial.ast.json")
    with pytest.raises(UnsupportedBuiltinError):
        translate_ast(program, module_name="request_financial")

    result = translate_ast(
        program,
        module_name="request_financial",
        compile_profile="diagnostic",
        allow_unsupported_request_stubs=True,
    )

    compile(result.code, "request_financial.py", "exec")
    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert "P2A_UNSUPPORTED_REQUEST" in codes
    assert "request.financial" in result.coverage["builtins"]
    assert result.metadata["parity_safe"] is False
    assert "unsupported_request_stub" in result.metadata["unsupported_features"]


@pytest.mark.xfail(reason="color.new() codegen handler not yet ported in 4.0 translator_parts")
def test_v0_7_color_new_and_plot_style_translate_from_pine2ast() -> None:
    program = parse_pine("""//@version=6
indicator("T")
plot(close, color=color.new(color.lime, 0), style=plot.style_linebr)
""")
    result = translate_ast(program, module_name="color_new_plot_style")

    compile(result.code, "color_new_plot_style.py", "exec")
    assert "pine_color.new" in result.code
    assert "color.new" in result.coverage["builtins"]


def test_v0_7_request_footprint_compiles_as_runtime_request() -> None:
    program = parse_pine("""//@version=6
indicator("T")
fp = request.footprint(10, 70, 300)
plot(not na(fp) ? fp.delta() : close)
""")
    production = translate_ast(program, module_name="footprint_prod")
    assert production.metadata["parity_safe"] is True
    assert "request_footprint_stub" not in production.metadata["unsupported_features"]

    result = translate_ast(
        program,
        module_name="footprint_diag",
        compile_profile="diagnostic",
        allow_unsupported_request_stubs=True,
    )

    compile(result.code, "footprint_diag.py", "exec")
    assert "request_footprint" in result.code
    assert "request.footprint" in result.coverage["builtins"]
    assert "request_footprint_stub" not in result.metadata["unsupported_features"]


def test_v0_7_supported_real_fixture_smoke_runs_or_skips_cleanly(tmp_path: Path) -> None:
    require_pine2ast_fixtures()
    program = load_ast(PINE2AST / "real_world_smoke/01_ma_indicator.ast.json")
    result = translate_ast(program, module_name="real_world_ma")
    paths = result.write_to(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "ast2python.cli.main", "smoke", str(paths["python"])],
        check=True,
        text=True,
        capture_output=True,
        timeout=30,
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
