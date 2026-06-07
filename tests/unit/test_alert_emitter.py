from __future__ import annotations

from ast2python.translator import translate_ast as _translate_ast
from tests.contract_metadata import with_valid_producer_metadata


def _literal(value, literal_type):
    return {"kind": "Literal", "literal_type": literal_type, "value": value}


def _argument(value, name=None):
    return {"kind": "Argument", "name": name, "value": value}


def _call(name, arguments, *, line):
    return {
        "kind": "CallExpr",
        "span": {"start_line": line, "start_col": 1},
        "callee": {"kind": "Identifier", "name": name},
        "arguments": arguments,
    }


def _program(*items):
    return with_valid_producer_metadata(
        {
            "kind": "Program",
            "language": "pine",
            "version": 6,
            "declaration": {
                "kind": "DeclarationStatement",
                "script_type": "indicator",
                "call": _call("indicator", [_argument(_literal("alerts", "string"))], line=1),
            },
            "items": list(items),
        }
    )


def test_alert_call_and_alertcondition_statement_lower_to_recorder_calls():
    alert_statement = {
        "kind": "ExpressionStatement",
        "span": {"start_line": 3, "start_col": 1},
        "expression": _call(
            "alert",
            [
                _argument(_literal("ping", "string")),
                _argument(_literal("once_per_bar", "string"), name="freq"),
            ],
            line=3,
        ),
    }
    alert_condition = {
        "kind": "AlertCondition",
        "span": {"start_line": 4, "start_col": 1},
        "condition": _literal(True, "bool"),
        "title": _literal("ready", "string"),
        "message": _literal("go", "string"),
    }

    result = _translate_ast(_program(alert_statement, alert_condition), module_name="alert_emitter")

    assert (
        "self._record_alert('alert', 'ping', freq='once_per_bar', source_map=\"L3\")" in result.code
    )
    assert (
        "self._record_alert('alertcondition', True, title='ready', message='go', source_map=\"L4\")"
        in result.code
    )
    assert {"alert", "alertcondition"} <= set(result.metadata["used_builtins"])
    compile(result.code, "alert_emitter.py", "exec")
