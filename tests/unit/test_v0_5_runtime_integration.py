import json
import subprocess
import sys
from pathlib import Path

import pytest

from ast2python.diagnostics import REQUEST_SECURITY_CAPTURE_UNSAFE
from ast2python.errors import TypeResolutionError, UnsupportedBuiltinError
from ast2python.translator import translate_ast as _translate_ast
from tests.contract_metadata import with_valid_producer_metadata


def translate_ast(program, *args, **kwargs):
    return _translate_ast(with_valid_producer_metadata(program), *args, **kwargs)


def decl(kind="indicator"):
    return {
        "kind": "DeclarationStatement",
        "script_type": kind,
        "call": {
            "kind": "CallExpr",
            "callee": {"kind": "Identifier", "name": kind},
            "arguments": [
                {
                    "kind": "Argument",
                    "name": None,
                    "value": {"kind": "Literal", "literal_type": "string", "value": "v05"},
                }
            ],
        },
    }


def lit(value, typ="int"):
    return {"kind": "Literal", "literal_type": typ, "value": value}


def ident(name):
    return {"kind": "Identifier", "name": name}


def member(obj, name):
    return {
        "kind": "MemberAccessExpr",
        "object": obj if isinstance(obj, dict) else ident(obj),
        "member": name,
    }


def arg(value, name=None):
    return {"kind": "Argument", "name": name, "value": value}


def call(name, args=None, span=None):
    callee = ident(name) if "." not in name else member(name.split(".")[0], name.split(".")[1])
    node = {"kind": "CallExpr", "callee": callee, "arguments": args or []}
    if span:
        node["span"] = span
    return node


def program(items, kind="indicator"):
    return with_valid_producer_metadata(
        {
            "kind": "Program",
            "language": "pine",
            "version": 6,
            "declaration": decl(kind),
            "items": items,
        }
    )


def test_generated_base_import_and_strategy_phase_contract_full_bar_lifecycle_no_fill():
    p = program(
        [
            {
                "kind": "ExpressionStatement",
                "span": {"start_line": 3, "start_col": 1},
                "expression": call(
                    "strategy.entry", [arg(lit("L", "string")), arg(member("strategy", "long"))]
                ),
            }
        ],
        kind="strategy",
    )
    result = translate_ast(p, module_name="phase")
    assert "GeneratedStrategyBase" in result.code
    assert "class GeneratedStrategy(GeneratedStrategyBase):" in result.code
    assert "self.ctx.attach_runtime(self.rt)" in result.code
    assert "run_generated_strategy" not in result.code
    assert "self._process_bar(bar)" in result.code
    assert "process_orders_for_bar" not in result.code
    compile(result.code, "phase.py", "exec")


def test_date_helpers_lower_to_runtime_timefunc():
    p = program(
        [
            {
                "kind": "VarDeclaration",
                "name": "y",
                "span": {"start_line": 3, "start_col": 1},
                "initializer": call("year", [arg(ident("time"))]),
            },
            {
                "kind": "VarDeclaration",
                "name": "m",
                "span": {"start_line": 4, "start_col": 1},
                "initializer": call("minute", []),
            },
        ]
    )
    result = translate_ast(p, module_name="dates")
    assert "self.rt.timefunc.year(runtime=self.rt)" in result.code
    assert "self.rt.timefunc.minute(runtime=self.rt)" in result.code
    assert {"year", "minute"}.issubset(set(result.metadata["used_builtins"]))


def test_history_reference_over_runtime_ta_call_materializes_expression_series():
    p = program(
        [
            {
                "kind": "ExpressionStatement",
                "span": {"start_line": 3, "start_col": 1},
                "expression": call(
                    "plot",
                    [
                        arg(
                            {
                                "kind": "HistoryRefExpr",
                                "span": {"start_line": 3, "start_col": 6},
                                "base": call(
                                    "ta.rsi",
                                    [arg(ident("close")), arg(lit(14))],
                                    span={"start_line": 3, "start_col": 6},
                                ),
                                "offset": lit(1),
                            }
                        ),
                        arg(lit("RSI_prev", "string")),
                    ],
                    span={"start_line": 3, "start_col": 1},
                ),
            }
        ]
    )
    result = translate_ast(p, module_name="expr_history_rsi", visual_policy="record")
    assert "self.rt.expr_history(rsi(" in result.code
    assert ".history(rsi(" not in result.code
    assert 'state_id="L3_C6_expr_history_1"' in result.code
    compile(result.code, "expr_history_rsi.py", "exec")


def test_history_reference_over_ema_and_atr_calls_materializes_expression_series():
    p = program(
        [
            {
                "kind": "ExpressionStatement",
                "span": {"start_line": 3, "start_col": 1},
                "expression": call(
                    "plot",
                    [
                        arg(
                            {
                                "kind": "HistoryRefExpr",
                                "span": {"start_line": 3, "start_col": 6},
                                "base": call(
                                    "ta.ema",
                                    [arg(ident("close")), arg(lit(20))],
                                    span={"start_line": 3, "start_col": 6},
                                ),
                                "offset": lit(1),
                            }
                        ),
                        arg(lit("EMA_prev", "string")),
                    ],
                    span={"start_line": 3, "start_col": 1},
                ),
            },
            {
                "kind": "ExpressionStatement",
                "span": {"start_line": 4, "start_col": 1},
                "expression": call(
                    "plot",
                    [
                        arg(
                            {
                                "kind": "HistoryRefExpr",
                                "span": {"start_line": 4, "start_col": 6},
                                "base": call(
                                    "ta.atr",
                                    [arg(lit(14))],
                                    span={"start_line": 4, "start_col": 6},
                                ),
                                "offset": lit(1),
                            }
                        ),
                        arg(lit("ATR_prev", "string")),
                    ],
                    span={"start_line": 4, "start_col": 1},
                ),
            },
        ]
    )
    result = translate_ast(p, module_name="expr_history_ema_atr", visual_policy="record")
    assert "self.rt.expr_history(ema(" in result.code
    assert "self.rt.expr_history(atr(" in result.code
    assert ".history(ema(" not in result.code
    assert ".history(atr(" not in result.code
    compile(result.code, "expr_history_ema_atr.py", "exec")


def test_reference_array_history_fails_before_runtime_and_copy_warns():
    arr_new = call("array.new", [arg(lit(0))])
    bad = program(
        [
            {
                "kind": "VarDeclaration",
                "name": "a",
                "type_ref": {"kind": "TypeRef", "name": "array"},
                "span": {"start_line": 3, "start_col": 1},
                "initializer": arr_new,
            },
            {
                "kind": "VarDeclaration",
                "name": "prev",
                "span": {"start_line": 4, "start_col": 1},
                "initializer": {"kind": "HistoryRefExpr", "base": ident("a"), "offset": lit(1)},
            },
        ]
    )
    with pytest.raises(TypeResolutionError):
        translate_ast(bad, module_name="array_history")

    ok = program(
        [
            {
                "kind": "VarDeclaration",
                "name": "a",
                "span": {"start_line": 3, "start_col": 1},
                "initializer": arr_new,
            },
            {
                "kind": "VarDeclaration",
                "name": "b",
                "span": {"start_line": 4, "start_col": 1},
                "initializer": call("array.copy", [arg(ident("a"))]),
            },
        ]
    )
    result = translate_ast(ok, module_name="array_copy")
    assert "self.a.current.copy()" in result.code
    assert any(d.code == "P2A_REFERENCE_COPY_POLICY" for d in result.diagnostics)


def test_request_security_capture_safety_warning_and_strict_error():
    p = program(
        [
            {
                "kind": "VarDeclaration",
                "name": "basis",
                "span": {"start_line": 3, "start_col": 1},
                "initializer": ident("close"),
            },
            {
                "kind": "VarDeclaration",
                "name": "htf",
                "span": {"start_line": 4, "start_col": 1},
                "initializer": call(
                    "request.security",
                    [arg(lit("AAPL", "string")), arg(lit("D", "string")), arg(ident("basis"))],
                ),
            },
        ]
    )
    result = translate_ast(p, module_name="security_capture")
    assert any(d.code == REQUEST_SECURITY_CAPTURE_UNSAFE for d in result.diagnostics)
    with pytest.raises(UnsupportedBuiltinError):
        translate_ast(p, strict=True, module_name="security_capture_strict")


def test_source_map_fixture_coverage_is_at_least_95_percent():
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "ast"
    for fixture in fixtures.glob("*.ast.json"):
        result = translate_ast(
            json.loads(fixture.read_text(encoding="utf-8")), module_name=fixture.stem
        )
        assert result.coverage["source_map_executable_line_ratio"] >= 0.95, fixture.name


def test_cli_smoke_runs_generated_code_against_sample_bars(tmp_path):
    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "ast" / "minimal_indicator.ast.json"
    )
    out = tmp_path / "generated"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ast2python.cli.main",
            "translate",
            str(fixture),
            "-o",
            str(out),
            "--module-name",
            "smoke_min",
        ],
        check=True,
        timeout=30,
    )
    proc = subprocess.run(
        [sys.executable, "-m", "ast2python.cli.main", "smoke", str(out / "smoke_min.py")],
        check=True,
        text=True,
        capture_output=True,
        timeout=30,
    )
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["runtime"] in {"executed", "skipped"}
    if payload["runtime"] == "executed":
        assert payload["bars"] == 2
