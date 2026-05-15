"""Tests for FixPack 3B: strategy.closedtrades / strategy.opentrades / strategy.risk translation."""
from __future__ import annotations

import pytest
from ast2python.translator import translate_ast


def _lit(value: object, literal_type: str) -> dict:
    return {"kind": "Literal", "literal_type": literal_type, "value": value}


def _arg(value: dict, name: str | None = None) -> dict:
    """Wrap a value node in an Argument node."""
    return {"kind": "Argument", "name": name, "value": value}


def _decl(title: str = "test", script_type: str = "strategy") -> dict:
    return {
        "kind": "DeclarationStatement",
        "script_type": script_type,
        "call": {
            "kind": "CallExpr",
            "callee": {"kind": "Identifier", "name": script_type},
            "arguments": [
                {"kind": "Argument", "name": None, "value": _lit(title, "string")},
            ],
        },
    }


def _program(items: list[dict], declaration: dict | None = None) -> dict:
    decl = declaration or _decl()
    return {
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
        "declaration": decl,
        "items": items,
    }


def _var_decl(name: str, initializer: dict) -> dict:
    """Top-level VarDeclaration (var/varip declarations at script level)."""
    return {
        "kind": "VarDeclaration",
        "explicit_qualifier": None,
        "mode": None,
        "name": name,
        "initializer": initializer,
    }


def _expr_stmt(expression: dict) -> dict:
    """Expression statement (standalone call, reassignment, etc. inside script body)."""
    return {"kind": "ExpressionStatement", "expression": expression}


def _call_expr(callee_parts: list[str], args: list[dict] | None = None) -> dict:
    """Build a CallExpr AST node from a list of member access parts.
    Args should already be wrapped in _arg() if they need names."""
    parts = callee_parts
    obj = {"kind": "Identifier", "name": parts[0]}
    for part in parts[1:-1]:
        obj = {"kind": "MemberAccessExpr", "object": obj, "member": part}
    callee = obj if len(parts) == 1 else {"kind": "MemberAccessExpr", "object": obj, "member": parts[-1]}
    return {"kind": "CallExpr", "callee": callee, "arguments": args or []}


class TestStrategyClosedTradesTranslation:
    """Test strategy.closedtrades.xxx translation — these are expression statements."""

    def _assert_generates(self, items: list[dict], expected_substr: str) -> None:
        program = _program(items)
        result = translate_ast(program, module_name="test_strategy_closedtrades")
        assert expected_substr in result.code, (
            f"Expected {expected_substr!r} in:\n{result.code}"
        )

    def test_closedtrades_entry_price(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "closedtrades", "entry_price"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.closedtrades_entry_price",
        )

    def test_closedtrades_exit_price(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "closedtrades", "exit_price"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.closedtrades_exit_price",
        )

    def test_closedtrades_entry_time(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "closedtrades", "entry_time"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.closedtrades_entry_time",
        )

    def test_closedtrades_exit_time(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "closedtrades", "exit_time"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.closedtrades_exit_time",
        )

    def test_closedtrades_profit(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "closedtrades", "profit"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.closedtrades_profit",
        )

    def test_closedtrades_size(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "closedtrades", "size"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.closedtrades_size",
        )

    def test_closedtrades_max_runup(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "closedtrades", "max_runup"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.closedtrades_max_runup",
        )

    def test_closedtrades_max_drawdown(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "closedtrades", "max_drawdown"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.closedtrades_max_drawdown",
        )


class TestStrategyOpenTradesTranslation:
    def _assert_generates(self, items: list[dict], expected_substr: str) -> None:
        program = _program(items)
        result = translate_ast(program, module_name="test_strategy_opentrades")
        assert expected_substr in result.code, (
            f"Expected {expected_substr!r} in:\n{result.code}"
        )

    def test_opentrades_entry_price(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "opentrades", "entry_price"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.opentrades_entry_price",
        )

    def test_opentrades_profit(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "opentrades", "profit"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.opentrades_profit",
        )

    def test_opentrades_size(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "opentrades", "size"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.opentrades_size",
        )

    def test_opentrades_max_runup(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "opentrades", "max_runup"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.opentrades_max_runup",
        )

    def test_opentrades_max_drawdown(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "opentrades", "max_drawdown"],
                [_arg(_lit(0, "int"))]
            ))],
            "self.ctx.opentrades_max_drawdown",
        )


def _identifier(name: str) -> dict:
    """Plain identifier (for Pine enums like strategy.direction.long)."""
    return {"kind": "Identifier", "name": name}


def _member_access(object: dict, member: str) -> dict:
    """Member access expression."""
    return {"kind": "MemberAccessExpr", "object": object, "member": member}


def _strategy_enum(path: list[str]) -> dict:
    """Build a strategy enum reference like strategy.direction.long as MemberAccessExpr chain."""
    obj = _identifier(path[0])
    for part in path[1:]:
        obj = _member_access(obj, part)
    return obj


class TestStrategyRiskTranslation:
    """strategy.risk.* tests — use literal args to avoid missing enum binder entries."""

    def _assert_generates(self, items: list[dict], expected_substr: str) -> None:
        program = _program(items)
        result = translate_ast(program, module_name="test_strategy_risk")
        assert expected_substr in result.code, (
            f"Expected {expected_substr!r} in:\n{result.code}"
        )

    def test_risk_allow_entry_in(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "risk", "allow_entry_in"],
                [_arg(_lit(1, "int"))]  # strategy.direction.long == 1
            ))],
            "self.ctx.risk_allow_entry_in",
        )

    def test_risk_max_drawdown(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "risk", "max_drawdown"],
                [_arg(_lit(20, "float")), _arg(_lit(1, "int"))]  # strategy.percent_of_equity == 1
            ))],
            "self.ctx.risk_max_drawdown",
        )

    def test_risk_max_intraday_loss(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "risk", "max_intraday_loss"],
                [_arg(_lit(5, "float")), _arg(_lit(1, "int"))]
            ))],
            "self.ctx.risk_max_intraday_loss",
        )

    def test_risk_max_position_size(self):
        self._assert_generates(
            [_expr_stmt(_call_expr(
                ["strategy", "risk", "max_position_size"],
                [_arg(_lit(100, "float")), _arg(_lit(1, "int"))]  # strategy.fixed == 1
            ))],
            "self.ctx.risk_max_position_size",
        )


class TestStrategyCloseAllTranslation:
    def test_close_all_no_args(self):
        program = _program([
            _expr_stmt(_call_expr(["strategy", "close_all"]))
        ])
        result = translate_ast(program, module_name="test_close_all")
        assert "self.ctx.close_all" in result.code

    def test_close_all_with_immediately(self):
        program = _program([
            _expr_stmt(_call_expr(
                ["strategy", "close_all"],
                [dict(name="immediately", value=_lit(True, "bool"))]
            ))
        ])
        result = translate_ast(program, module_name="test_close_all")
        assert "self.ctx.close_all" in result.code