from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
import re

from ast2python.translator import translate_ast
from tests.contract_metadata import with_valid_producer_metadata


def _literal(value: object, literal_type: str) -> dict:
    return {"kind": "Literal", "literal_type": literal_type, "value": value}


def _identifier(name: str) -> dict:
    return {"kind": "Identifier", "name": name}


def _span(line: int, col: int = 1) -> dict:
    return {
        "start_line": line,
        "start_col": col,
        "end_line": line,
        "end_col": col + 1,
    }


def _history(name: str, line: int, col: int) -> dict:
    return {
        "kind": "HistoryRefExpr",
        "span": _span(line, col),
        "base": {"kind": "Identifier", "span": _span(line, col), "name": name},
        "offset": _literal(1, "int"),
    }


def _binary(op: str, left: dict, right: dict) -> dict:
    return {"kind": "BinaryExpr", "op": op, "left": left, "right": right}


def _unary(op: str, operand: dict) -> dict:
    return {"kind": "UnaryExpr", "op": op, "operand": operand}


def _arg(value: dict, name: str | None = None) -> dict:
    return {"kind": "Argument", "name": name, "value": value}


def _call(name: str, args: list[dict] | None = None) -> dict:
    return {
        "kind": "CallExpr",
        "callee": {"kind": "Identifier", "name": name},
        "arguments": args or [],
    }


def _program(*items: dict) -> dict:
    return with_valid_producer_metadata(
        {
            "kind": "Program",
            "language": "pine",
            "version": 6,
            "declaration": {
                "kind": "DeclarationStatement",
                "script_type": "indicator",
                "call": _call("indicator", [_arg(_literal("function returns", "string"))]),
            },
            "items": list(items),
        }
    )


def test_multiline_function_returns_final_var_declaration_value() -> None:
    program = _program(
        {
            "kind": "FunctionDeclaration",
            "name": "f_last_decl",
            "parameters": [
                {"kind": "Parameter", "name": "src", "type_ref": None},
            ],
            "body": {
                "kind": "Block",
                "statements": [
                    {
                        "kind": "VarDeclaration",
                        "name": "basis",
                        "mode": None,
                        "explicit_qualifier": None,
                        "type_ref": None,
                        "initializer": _identifier("src"),
                    },
                    {
                        "kind": "VarDeclaration",
                        "name": "_zigzag",
                        "mode": None,
                        "explicit_qualifier": None,
                        "type_ref": None,
                        "initializer": _literal(42.0, "float"),
                    },
                ],
            },
        },
        {
            "kind": "VarDeclaration",
            "name": "out",
            "mode": None,
            "explicit_qualifier": None,
            "type_ref": None,
            "initializer": _call("f_last_decl", [_arg(_literal(1.0, "float"))]),
        },
    )

    result = translate_ast(program, module_name="function_return_semantics")

    assert "return zigzag" in result.code, result.code
    namespace: dict[str, Any] = {}
    exec(compile(result.code, "function_return_semantics.py", "exec"), namespace)
    generated_indicator = cast(Any, namespace["GeneratedIndicator"])
    script = generated_indicator(runtime=SimpleNamespace(contract_version="1.4"))
    assert script.f_last_decl(1.0) == 42.0


def test_local_variable_history_uses_one_stable_state_id_per_variable() -> None:
    rising_now = _identifier("rising")
    rising_prev_positive_branch = _history("rising", line=21, col=33)
    rising_prev_negative_branch = _history("rising", line=22, col=33)
    program = _program(
        {
            "kind": "FunctionDeclaration",
            "name": "f_turn",
            "parameters": [
                {"kind": "Parameter", "name": "src", "type_ref": None},
            ],
            "body": {
                "kind": "Block",
                "statements": [
                    {
                        "kind": "VarDeclaration",
                        "name": "rising",
                        "mode": None,
                        "explicit_qualifier": None,
                        "type_ref": None,
                        "initializer": _binary(
                            ">=",
                            _identifier("src"),
                            _history("src", line=20, col=20),
                        ),
                    },
                    {
                        "kind": "VarDeclaration",
                        "name": "pulse",
                        "mode": None,
                        "explicit_qualifier": None,
                        "type_ref": None,
                        "initializer": {
                            "kind": "ConditionalExpr",
                            "condition": _binary(
                                "and",
                                rising_now,
                                _unary("not", rising_prev_positive_branch),
                            ),
                            "then": _literal(1, "int"),
                            "else": {
                                "kind": "ConditionalExpr",
                                "condition": _binary(
                                    "and",
                                    _unary("not", _identifier("rising")),
                                    rising_prev_negative_branch,
                                ),
                                "then": _literal(-1, "int"),
                                "else": _literal(0, "int"),
                            },
                        },
                    },
                ],
            },
        },
        {
            "kind": "VarDeclaration",
            "name": "out",
            "mode": None,
            "explicit_qualifier": None,
            "type_ref": None,
            "initializer": _call("f_turn", [_arg(_literal(1.0, "float"))]),
        },
    )

    result = translate_ast(program, module_name="function_history_semantics")

    rising_history_ids = re.findall(
        r'expr_history\(rising, 1, state_id=_cs_id \+ "([^"]+)"\)', result.code
    )
    assert len(rising_history_ids) == 2, result.code
    assert len(set(rising_history_ids)) == 1, result.code
