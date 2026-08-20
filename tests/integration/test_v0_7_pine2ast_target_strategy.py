from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ast2python.ast.schema import ensure_program_node
from ast2python.coverage import static_coverage_report
from ast2python.errors import UnsupportedBuiltinError
from ast2python.translator import translate_ast as _translate_ast
from ast2python.version import __version__
from tests.contract_metadata import with_valid_producer_metadata


def translate_ast(program, *args, **kwargs):
    return _translate_ast(with_valid_producer_metadata(program), *args, **kwargs)


def parse_pine(source: str) -> dict:
    from pine2ast.api import ParseOptions, parse_code

    result = parse_code(source, ParseOptions(run_semantic=True))
    errors = [diag for diag in result.diagnostics if diag.severity.value in {"ERROR", "FATAL"}]
    assert errors == []
    return result.ast.to_dict()


@pytest.mark.parametrize(
    "fixture_name, source, expected, external",
    [
        (
            "generic_array",
            """//@version=6
indicator("Array")
var array<float> values = array.new<float>()
sum = 0.0
for item in values
    sum += item
plot(sum)
""",
            {"array.new"},
            False,
        ),
        (
            "map_matrix_types",
            """//@version=6
indicator("Map matrix")
var matrix<float> m = matrix.new<float>(2, 2, 0.0)
var map<string, float> mp = map.new<string, float>()
plot(close)
""",
            {"map.new", "matrix.new"},
            False,
        ),
        (
            "import_alias_external_call",
            """//@version=6
indicator("Import")
import user/Lib/1 as lib
x = lib.someFunction(close)
plot(close)
""",
            {"lib.someFunction"},
            True,
        ),
        (
            "strategy_exit",
            """//@version=6
strategy("Exit")
strategy.entry("L", strategy.long)
strategy.exit("LX", "L", stop=low, limit=high)
""",
            {"strategy.entry", "strategy.exit"},
            False,
        ),
        (
            "input_source_strategy_state",
            """//@version=6
strategy("Input Source Strategy", overlay=true)
src = close
len = input.int(21, "Length", minval=1, options=[10, 21, 50])
ma = ta.ema(src, len)
if ta.crossover(src, ma) and strategy.position_size <= 0
    strategy.entry("L", strategy.long)
plot(ma, color=color.orange)
""",
            {"input.int", "ta.ema", "strategy.entry"},
            False,
        ),
    ],
)
def test_v0_7_real_pine2ast_fixtures_translate_and_compile(
    fixture_name: str, source: str, expected: set[str], external: bool
) -> None:
    program = parse_pine(source)
    static = static_coverage_report(ensure_program_node(program))
    assert static["schema_supported_ratio"] >= 0.98

    if external:
        with pytest.raises(UnsupportedBuiltinError):
            translate_ast(program, module_name=fixture_name)
        result = translate_ast(
            program,
            module_name=fixture_name,
            compile_profile="diagnostic",
            allow_external_library_stubs=True,
        )
        assert result.metadata["parity_safe"] is False
        assert "external_library_stubs" in result.metadata["unsupported_features"]
    else:
        result = translate_ast(program, module_name=fixture_name)

    compile(result.code, f"{fixture_name}.py", "exec")

    assert result.coverage["source_map_executable_line_ratio"] >= 0.95
    assert expected <= set(result.coverage["builtins"])
    assert result.metadata["generator_milestone"] == f"v{__version__}"


def test_v0_7_unsupported_request_financial_is_diagnostic_not_placeholder_crash() -> None:
    program = parse_pine(
        """//@version=6
indicator("Financial NA")
eps = request.financial(syminfo.tickerid, "EARNINGS_PER_SHARE", "FQ")
confirmed = barstate.isconfirmed and not na(eps)
plot(confirmed ? eps : na)
"""
    )
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


def test_v0_7_color_new_and_plot_style_translate_from_pine2ast() -> None:
    program = parse_pine(
        """//@version=6
indicator("T")
plot(close, color=color.new(color.lime, 0), style=plot.style_linebr)
"""
    )
    result = translate_ast(program, module_name="color_new_plot_style")

    compile(result.code, "color_new_plot_style.py", "exec")
    assert "pine_color.new" in result.code
    assert "color.new" in result.coverage["builtins"]


def test_v0_7_request_footprint_compiles_as_runtime_request() -> None:
    program = parse_pine(
        """//@version=6
indicator("T")
fp = request.footprint(10, 70, 300)
plot(not na(fp) ? fp.delta() : close)
"""
    )
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


def test_v0_7_supported_real_fixture_smoke_executes(tmp_path: Path) -> None:
    program = parse_pine(
        """//@version=6
indicator("MA Indicator", overlay=true)
len = input.int(20, title="Length", minval=1)
ma = ta.sma(close, len)
plot(ma)
"""
    )
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
    assert payload["runtime"] == "executed"


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
