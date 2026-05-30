from __future__ import annotations

from ast2python.translator import translate_ast


def _lit(value: object, literal_type: str) -> dict[str, object]:
    return {"kind": "Literal", "literal_type": literal_type, "value": value}


def test_strategy_realtime_and_broker_flags_lower_to_strategy_context_and_run_loop() -> None:
    program = {
        "kind": "Program",
        "language": "pine",
        "version": 6,
        "producer_metadata": {
            "contract": "pain.ast_contract.v1",
            "producer": {"name": "pine2ast", "version": "test"},
            "schema_version": "1.0",
            "pine_language_version": 6,
            "runtime_contract": "runtime_contract_v1_4",
            "parser_gate": "pass",
            "semantic_gate": "pass",
        },
        "declaration": {
            "kind": "DeclarationStatement",
            "script_type": "strategy",
            "call": {
                "kind": "CallExpr",
                "callee": {"kind": "Identifier", "name": "strategy"},
                "arguments": [
                    {"kind": "Argument", "name": None, "value": _lit("D", "string")},
                    {
                        "kind": "Argument",
                        "name": "process_orders_on_close",
                        "value": _lit(True, "bool"),
                    },
                    {
                        "kind": "Argument",
                        "name": "calc_on_order_fills",
                        "value": _lit(True, "bool"),
                    },
                    {"kind": "Argument", "name": "calc_on_every_tick", "value": _lit(True, "bool")},
                    {"kind": "Argument", "name": "use_bar_magnifier", "value": _lit(True, "bool")},
                    {"kind": "Argument", "name": "margin_long", "value": _lit(50, "int")},
                    {"kind": "Argument", "name": "margin_short", "value": _lit(75, "int")},
                    {
                        "kind": "Argument",
                        "name": "fill_orders_on_standard_ohlc",
                        "value": _lit(True, "bool"),
                    },
                    {
                        "kind": "Argument",
                        "name": "backtest_fill_limits_assumption",
                        "value": _lit(1, "int"),
                    },
                    {
                        "kind": "Argument",
                        "name": "close_entries_rule",
                        "value": _lit("ANY", "string"),
                    },
                    {"kind": "Argument", "name": "max_lines_count", "value": _lit(10, "int")},
                    {"kind": "Argument", "name": "max_labels_count", "value": _lit(20, "int")},
                    {"kind": "Argument", "name": "max_boxes_count", "value": _lit(30, "int")},
                ],
            },
        },
        "items": [],
    }
    result = translate_ast(
        program,
        module_name="iter_d_flags",
        compile_profile="diagnostic",
        allow_realtime_local_simulation=True,
    )
    assert result.metadata["parity_safe"] is False
    for expected in (
        "process_orders_on_close=True",
        "calc_on_order_fills=True",
        "calc_on_every_tick=True",
        "use_bar_magnifier=True",
        "margin_long=50",
        "margin_short=75",
        "fill_orders_on_standard_ohlc=True",
        "backtest_fill_limits_assumption=1",
        "close_entries_rule='ANY'",
        "max_lines_count=10",
        "max_labels_count=20",
        "max_boxes_count=30",
        "from pinelib.backtest import run_generated_strategy",
        "result = run_generated_strategy(self, self.rt, self.ctx, bars)",
    ):
        assert expected in result.code
    compile(result.code, "iter_d_flags.py", "exec")
