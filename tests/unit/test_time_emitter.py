from datetime import UTC, datetime

import pytest

from ast2python.errors import UnsupportedBuiltinError
from ast2python.translator import translate_ast as _translate_ast
from tests.contract_metadata import with_valid_producer_metadata


def _literal(value, literal_type):
    return {"kind": "Literal", "literal_type": literal_type, "value": value}


def _timestamp_call(*args):
    return {
        "kind": "CallExpr",
        "callee": {"kind": "Identifier", "name": "timestamp"},
        "arguments": [{"kind": "Argument", "name": None, "value": arg} for arg in args],
    }


def _program(expression):
    return with_valid_producer_metadata(
        {
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
                            "value": _literal("time", "string"),
                        }
                    ],
                },
            },
            "items": [
                {
                    "kind": "VarDeclaration",
                    "name": "x",
                    "initializer": expression,
                }
            ],
        }
    )


def _translate(expression):
    return _translate_ast(_program(expression), module_name="time_emitter")


def test_timestamp_string_literal_lowers_to_unix_milliseconds():
    result = _translate(_timestamp_call(_literal("2026-05-07 20:45:00 +0000", "string")))

    expected = int(datetime(2026, 5, 7, 20, 45, tzinfo=UTC).timestamp() * 1000)
    assert f"self.x.set_current({expected})" in result.code
    assert "timestamp" in result.metadata["used_builtins"]
    compile(result.code, "time_emitter.py", "exec")


def test_timestamp_components_with_unknown_timezone_fail_closed():
    expression = _timestamp_call(
        _literal("Not/AZone", "string"),
        _literal(2026, "int"),
        _literal(5, "int"),
        _literal(7, "int"),
        _literal(20, "int"),
        _literal(45, "int"),
    )

    with pytest.raises(UnsupportedBuiltinError, match="unsupported timezone"):
        _translate(expression)
