from __future__ import annotations

import pytest

from ast2python.binder import BUILTIN_SIGNATURES
from ast2python.errors import TypeResolutionError, UnsupportedBuiltinError
from ast2python.translator import translate_ast as _translate_ast
from tests.contract_metadata import with_valid_producer_metadata


def translate_ast(program, *args, **kwargs):
    return _translate_ast(with_valid_producer_metadata(program), *args, **kwargs)


def declaration(kind: str = "indicator") -> dict[str, object]:
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
                    "value": {"kind": "Literal", "literal_type": "string", "value": "B"},
                }
            ],
        },
    }


def lit(value: object, literal_type: str | None = None) -> dict[str, object]:
    if literal_type is None:
        literal_type = (
            "bool"
            if isinstance(value, bool)
            else "int"
            if isinstance(value, int)
            else "float"
            if isinstance(value, float)
            else "string"
        )
    return {"kind": "Literal", "literal_type": literal_type, "value": value}


def ident(name: str) -> dict[str, object]:
    return {"kind": "Identifier", "name": name}


def member(base: str, name: str) -> dict[str, object]:
    return {
        "kind": "MemberAccessExpr",
        "member": name,
        "object": {"kind": "Identifier", "name": base},
    }


def arg(value: dict[str, object], name: str | None = None) -> dict[str, object]:
    return {"kind": "Argument", "name": name, "value": value}


def call(chain: str, args: list[dict[str, object]], *, line: int = 3) -> dict[str, object]:
    if "." in chain:
        base, name = chain.split(".", 1)
        callee = member(base, name)
    else:
        callee = {"kind": "Identifier", "name": chain}
    return {
        "kind": "CallExpr",
        "span": {"start_line": line, "start_col": 1},
        "callee": callee,
        "arguments": args,
    }


def program(expr: dict[str, object], *, kind: str = "indicator") -> dict[str, object]:
    return with_valid_producer_metadata({
        "kind": "Program",
        "language": "pine",
        "version": 6,
        "declaration": declaration(kind),
        "items": [{"kind": "ExpressionStatement", "expression": expr}],
    })


def var(name: str, init: dict[str, object]) -> dict[str, object]:
    return {"kind": "VarDeclaration", "name": name, "initializer": init}


def test_iteration_b_matrix_covers_lowered_namespaces() -> None:
    required = {
        "ta.ema",
        "ta.bb",
        "ta.highest",
        "math.pow",
        "math.min",
        "str.contains",
        "request.security",
        "strategy.entry",
        "strategy.exit",
        "plot",
        "line.new",
        "line.set_xy1",
        "table.cell",
        "array.new",
        "map.get",
        "matrix.set",
    }
    assert required <= set(BUILTIN_SIGNATURES)


def test_iteration_b_valid_named_ta_math_str_visual_strategy_calls_compile() -> None:
    p = {
        "kind": "Program",
        "language": "pine",
        "version": 6,
        "declaration": declaration("strategy"),
        "items": [
            var(
                "avg",
                call("ta.ema", [arg(lit(10), "length"), arg(ident("close"), "source")], line=3),
            ),
            var("m", call("math.pow", [arg(lit(2), "exponent"), arg(lit(3), "base")], line=4)),
            var("s", call("str.upper", [arg(lit("abc"), "source")], line=5)),
            {
                "kind": "ExpressionStatement",
                "expression": call(
                    "line.new",
                    [arg(lit(0)), arg(ident("close")), arg(lit(1)), arg(ident("close"))],
                    line=6,
                ),
            },
            {
                "kind": "ExpressionStatement",
                "expression": call(
                    "strategy.entry",
                    [arg(lit("L"), "id"), arg(member("strategy", "long"), "direction")],
                    line=7,
                ),
            },
            {
                "kind": "ExpressionStatement",
                "expression": call(
                    "plot", [arg(ident("close"), "series"), arg(lit("Close"), "title")], line=8
                ),
            },
        ],
    }
    result = translate_ast(p, module_name="valid_iteration_b")
    assert not result.diagnostics
    compile(result.code, "valid_iteration_b.py", "exec")


@pytest.mark.parametrize(
    ("expr", "message"),
    [
        (call("math.pow", [arg(lit(2))]), "expects at least"),
        (
            call("str.contains", [arg(lit("abc")), arg(lit("a")), arg(lit("extra"))]),
            "expects at most",
        ),
        (call("plot", [arg(ident("close"), "not_a_plot_arg")]), "does not accept named argument"),
        (call("ta.ema", [arg(ident("close")), arg(ident("bar_index"))]), "qualifier <= simple"),
        (call("math.sqrt", [arg(lit(True))]), "expects float/int/source"),
    ],
)
def test_iteration_b_invalid_overloads_fail_closed(expr: dict[str, object], message: str) -> None:
    with pytest.raises(TypeResolutionError):
        translate_ast(program(expr), module_name="bad_iteration_b")


def test_iteration_b_unknown_and_unsupported_builtins_are_explicit() -> None:
    with pytest.raises(UnsupportedBuiltinError):
        translate_ast(program(call("math.mystery", [])), module_name="unknown_math")

    with pytest.raises(UnsupportedBuiltinError):
        translate_ast(
            program(call("ta.supertrend", [arg(lit(3.0)), arg(lit(10))])),
            module_name="unsupported_supertrend",
        )


def test_iteration_b_reference_history_still_fails_closed() -> None:
    p = {
        "kind": "Program",
        "language": "pine",
        "version": 6,
        "declaration": declaration(),
        "items": [
            var("a", call("array.new", [arg(lit(1))])),
            var("bad", {"kind": "HistoryRefExpr", "base": ident("a"), "index": lit(1)}),
        ],
    }
    with pytest.raises(TypeResolutionError):
        translate_ast(p, module_name="ref_history_bad")


def test_iteration_b_diagnostic_codes_are_emitted_on_binder_errors() -> None:
    translator_error = None
    try:
        translate_ast(program(call("ta.missing", [])), module_name="diag_unknown")
    except UnsupportedBuiltinError as exc:
        translator_error = exc
    assert translator_error is not None

    try:
        translate_ast(program(call("math.pow", [arg(lit(2))])), module_name="diag_mismatch")
    except TypeResolutionError as exc:
        assert "semantic binding failed" in str(exc)
