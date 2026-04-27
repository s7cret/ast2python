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
