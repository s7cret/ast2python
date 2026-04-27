import json
from pathlib import Path
from typing import Any, cast

from ast2python.diagnostics import WARNING_NESTED_SECURITY
from ast2python.translator import translate_ast


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ast"


def load_fixture(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def test_contract_header_and_minimal_indicator_compiles():
    result = translate_ast(load_fixture("minimal_indicator.ast.json"), module_name="minimal_indicator")
    assert 'REQUIRED_RUNTIME_CONTRACT = "1.4"' in result.code
    assert "class GeneratedIndicator" in result.code
    assert "# pine:L3 basis = close + open" in result.code
    compile(result.code, "minimal_indicator.py", "exec")


def test_strategy_declaration_metadata_and_context_mapping():
    result = translate_ast(load_fixture("strategy_declaration.ast.json"), module_name="strategy_declaration")
    assert "self.ctx = StrategyContext(" in result.code
    assert "initial_capital=100000" in result.code
    assert "commission_type='percent'" in result.code
    assert result.metadata["declaration"]["kind"] == "strategy"
    assert result.metadata["declaration"]["arguments"]["commission_type"] == "percent"
    compile(result.code, "strategy_declaration.py", "exec")


def test_request_security_callable_generation_and_state_ids():
    result = translate_ast(load_fixture("request_security.ast.json"), module_name="request_security")
    assert "from pinelib.ta import ema" in result.code
    assert "lambda request_rt: ema(request_rt.close, 200, runtime=request_rt" in result.code
    assert 'state_id="L4_C47_ema_1"' in result.code
    assert 'state_id="L4_C7_security_1"' in result.code
    assert 'lookahead=\'barmerge.lookahead_on\'' in result.code
    assert result.metadata["inputs"][0]["pine_name"] == "htf"
    compile(result.code, "request_security.py", "exec")


def test_nested_request_security_emits_diagnostic():
    result = translate_ast(load_fixture("nested_request_security.ast.json"), module_name="nested_request")
    codes = [item.code for item in result.diagnostics]
    assert WARNING_NESTED_SECURITY in codes


def test_v0_2_tuple_history_input_metadata_and_color_member_access():
    result = translate_ast(load_fixture("v0_2_foundation_indicator.ast.json"), module_name="v0_2_foundation")
    assert "from pinelib.colors import color as pine_color" in result.code
    assert "from pinelib.ta import bb" in result.code
    assert 'state_id="L4_C25_bb_1"' in result.code
    assert "_basis, _upper, _lower = bb(self.rt.close, self.len_.current, 2, runtime=self.rt" in result.code
    assert "self.prev.set_current(self.basis[1])" in result.code
    assert "pine_color.aqua" in result.code
    input_meta = result.metadata["inputs"][0]
    assert input_meta["title"] == "Length"
    assert input_meta["group"] == "Core"
    assert input_meta["inline"] == "L"
    assert input_meta["tooltip"] == "EMA length"
    assert result.metadata["generator_milestone"] == "v0.6.0"
    assert any(item["pine_line"] == 4 for item in result.source_map)
    compile(result.code, "v0_2_foundation.py", "exec")


def test_v0_2_strategy_loop_uses_pine_range_history_and_barstate():
    result = translate_ast(load_fixture("v0_2_strategy_loop.ast.json"), module_name="v0_2_strategy_loop")
    assert "from pinelib.core import PineRuntime, na, pine_bool, pine_range" in result.code
    assert "process_orders_on_close=True" in result.code
    assert "for i in pine_range(0, 2):" in result.code
    assert "self.sum_.set_current(self.sum_.current + (self.rt.close[i]))" in result.code
    assert "if pine_bool(self.rt.barstate.isconfirmed):" in result.code
    assert "self.ctx.entry('L', \"long\"" in result.code
    compile(result.code, "v0_2_strategy_loop.py", "exec")

def test_v0_3_input_metadata_time_calls_and_typeinfo():
    program = {
        "kind": "Program", "language": "pine", "version": 6,
        "declaration": {"kind": "DeclarationStatement", "script_type": "indicator", "call": {"kind": "CallExpr", "callee": {"kind": "Identifier", "name": "indicator"}, "arguments": [{"kind": "Argument", "name": None, "value": {"kind": "Literal", "literal_type": "string", "value": "Inputs"}}, {"kind": "Argument", "name": "max_lines_count", "value": {"kind": "Literal", "literal_type": "int", "value": 10}}]}},
        "items": [
            {"kind": "VarDeclaration", "name": "sess", "span": {"start_line": 3, "start_col": 1}, "initializer": {"kind": "CallExpr", "callee": {"kind": "MemberAccessExpr", "member": "session", "object": {"kind": "Identifier", "name": "input"}}, "arguments": [{"kind": "Argument", "name": None, "value": {"kind": "Literal", "literal_type": "string", "value": "0930-1600"}}, {"kind": "Argument", "name": "title", "value": {"kind": "Literal", "literal_type": "string", "value": "Session"}}, {"kind": "Argument", "name": "confirm", "value": {"kind": "Literal", "literal_type": "bool", "value": True}}]}},
            {"kind": "VarDeclaration", "name": "src", "span": {"start_line": 4, "start_col": 1}, "initializer": {"kind": "CallExpr", "callee": {"kind": "MemberAccessExpr", "member": "source", "object": {"kind": "Identifier", "name": "input"}}, "arguments": [{"kind": "Argument", "name": None, "value": {"kind": "Identifier", "name": "close"}}]}},
            {"kind": "VarDeclaration", "name": "t", "span": {"start_line": 5, "start_col": 1}, "initializer": {"kind": "CallExpr", "span": {"start_line": 5, "start_col": 5}, "callee": {"kind": "Identifier", "name": "time"}, "arguments": [{"kind": "Argument", "name": None, "value": {"kind": "MemberAccessExpr", "member": "period", "object": {"kind": "Identifier", "name": "timeframe"}}}, {"kind": "Argument", "name": None, "value": {"kind": "Identifier", "name": "sess"}}]}},
            {"kind": "VarDeclaration", "name": "tc", "span": {"start_line": 6, "start_col": 1}, "initializer": {"kind": "CallExpr", "span": {"start_line": 6, "start_col": 6}, "callee": {"kind": "Identifier", "name": "time_close"}, "arguments": [{"kind": "Argument", "name": None, "value": {"kind": "Literal", "literal_type": "string", "value": "60"}}, {"kind": "Argument", "name": "session", "value": {"kind": "Identifier", "name": "sess"}}]}}
        ],
    }
    result = translate_ast(program, module_name="v0_3_inputs_time")
    assert "self.rt.timefunc.time(self.rt.timeframe.period, self.sess.current, runtime=self.rt" in result.code
    assert "self.rt.timefunc.time_close('60', session=self.sess.current, runtime=self.rt" in result.code
    assert "self.src.set_current(self.params.get(\"src\", self.rt.close))" in result.code
    assert result.metadata["declaration"]["arguments"]["max_lines_count"] == 10
    assert result.metadata["inputs"][0]["confirm"] is True
    assert result.metadata["types"]["global:sess"]["qualifier"] == "series"
    assert result.metadata["generator_milestone"] == "v0.6.0"
    compile(result.code, "v0_3_inputs_time.py", "exec")


def test_v0_3_bool_na_validation_and_unknown_overload():
    bool_na = {"kind": "Program", "language": "pine", "version": 6, "declaration": {"kind": "DeclarationStatement", "script_type": "indicator", "call": {"kind": "CallExpr", "callee": {"kind": "Identifier", "name": "indicator"}, "arguments": [{"kind": "Argument", "name": None, "value": {"kind": "Literal", "literal_type": "string", "value": "Bool"}}]}}, "items": [{"kind": "VarDeclaration", "name": "bad", "span": {"start_line": 3, "start_col": 1}, "initializer": {"kind": "CallExpr", "callee": {"kind": "Identifier", "name": "na"}, "arguments": [{"kind": "Argument", "name": None, "value": {"kind": "Literal", "literal_type": "bool", "value": True}}]}}]}
    import pytest
    from ast2python.errors import TypeResolutionError, UnsupportedBuiltinError
    with pytest.raises(TypeResolutionError):
        translate_ast(bool_na, module_name="bool_na")
    unknown = {"kind": "Program", "language": "pine", "version": 6, "declaration": bool_na["declaration"], "items": [{"kind": "ExpressionStatement", "expression": {"kind": "CallExpr", "span": {"start_line": 4, "start_col": 1}, "callee": {"kind": "Identifier", "name": "mystery"}, "arguments": []}}]}
    with pytest.raises(UnsupportedBuiltinError):
        translate_ast(unknown, module_name="unknown_call")


def test_v0_3_nested_request_strict_fails():
    import pytest
    from ast2python.errors import UnsupportedBuiltinError
    with pytest.raises(UnsupportedBuiltinError):
        translate_ast(load_fixture("nested_request_security.ast.json"), strict=True, module_name="nested_strict")
