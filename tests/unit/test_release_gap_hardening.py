from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest

from ast2python.ast.schema import ASTNode
from ast2python.cli.main import main as cli_main
from ast2python.cli.parser import build_parser
from ast2python.context import TranslationContext
from ast2python.diagnostics import (
    REQUEST_SECURITY_CAPTURE_UNSAFE,
    VISUAL_CALL_FORBIDDEN,
    VISUAL_FRONTEND_DIAGNOSTIC_IGNORED,
    Severity,
)
from ast2python.errors import TypeResolutionError, UnsupportedBuiltinError, UnsupportedNodeError
from ast2python.quality import architecture_report, duplicate_report
from ast2python.release import release_report
from ast2python.translator import Translator
from ast2python.translator import translate_ast as _translate_ast
from ast2python.translator_mixins.metadata_inputs import _default_for_type, build_input_metadata
from ast2python.translator_mixins.metadata_requests import (
    contains_any_request_call,
    contains_request_call,
    diagnose_request_security_captures,
    diagnose_request_security_lower_tf_safety,
    is_lower_tf_safe_immutable_scalar_capture,
)
from ast2python.translator_mixins.metadata_type_info import _type_ref_name, infer_dtype
from ast2python.visuals import (
    frontend_diagnostic_visual_call,
    normalize_visual_policy,
    visual_call_from_call_chain,
)
from tests.contract_metadata import with_valid_producer_metadata


def ident(name: str) -> dict[str, Any]:
    return {"kind": "Identifier", "name": name}


def lit(value: Any, literal_type: str | None = None) -> dict[str, Any]:
    if literal_type is None:
        literal_type = (
            "bool"
            if isinstance(value, bool)
            else (
                "int"
                if isinstance(value, int)
                else "float" if isinstance(value, float) else "string"
            )
        )
    return {"kind": "Literal", "literal_type": literal_type, "value": value}


def member(base: str, name: str) -> dict[str, Any]:
    return {"kind": "MemberAccessExpr", "object": ident(base), "member": name}


def arg(value: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    return {"kind": "Argument", "name": name, "value": value}


def call(chain: str, args: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if "." in chain:
        base, name = chain.split(".", 1)
        callee = member(base, name)
    else:
        callee = ident(chain)
    return {"kind": "CallExpr", "callee": callee, "arguments": args or []}


def stmt(expr: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "ExpressionStatement", "expression": expr}


def var(
    name: str, init: dict[str, Any], *, mode: str = "normal", type_name: str | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": "VarDeclaration",
        "name": name,
        "mode": mode,
        "initializer": init,
    }
    if type_name is not None:
        data["type_ref"] = {"kind": "TypeRef", "name": type_name}
    return data


def program(
    items: list[dict[str, Any]] | dict[str, Any], *, diagnostics: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    if isinstance(items, dict):
        items = [items]
    raw = {
        "kind": "Program",
        "language": "pine",
        "version": 6,
        "declaration": {
            "kind": "DeclarationStatement",
            "script_type": "indicator",
            "call": call("indicator", [arg(lit("Hardening", "string"))]),
        },
        "items": items,
    }
    if diagnostics is not None:
        raw["diagnostics"] = diagnostics
    return with_valid_producer_metadata(raw)


def translate(program_dict: dict[str, Any], **kwargs: Any):
    return _translate_ast(
        program_dict, module_name=kwargs.pop("module_name", "hardening"), **kwargs
    )


def test_visual_policy_default_drops_plot_and_frontend_visual_diagnostic() -> None:
    p = program(
        stmt(call("plot", [arg(ident("close")), arg(lit("Close", "string"))])),
        diagnostics=[
            {
                "code": "P2A1507",
                "severity": "error",
                "message": "Builtin plot has no runtime-equivalent visual output under runtime_contract v1.4.",
                "details": {"builtin": "plot"},
            }
        ],
    )
    result = translate(p)
    assert "plot_recorder.record_plot" not in result.code
    assert "None" in result.code
    assert result.metadata["visual_policy"] == "drop"
    assert [d.code for d in result.diagnostics] == [VISUAL_FRONTEND_DIAGNOSTIC_IGNORED]


def test_visual_policy_record_and_error_modes() -> None:
    p = program(stmt(call("plot", [arg(ident("close")), arg(lit("Close", "string"))])))
    recorded = translate(p, visual_policy="record", module_name="visual_record")
    assert "plot_recorder.record_plot" in recorded.code
    assert recorded.metadata["visual_policy"] == "record"

    with pytest.raises(UnsupportedBuiltinError):
        translate(p, visual_policy="error", module_name="visual_error")

    translator = Translator(visual_policy="error")
    with pytest.raises(UnsupportedBuiltinError):
        translator.translate_program(p, module_name="visual_error_direct")
    assert translator.ctx.diagnostics[-1].code == VISUAL_CALL_FORBIDDEN


def test_visual_helper_normalization_and_diagnostic_detection() -> None:
    assert normalize_visual_policy("skip") == "drop"
    assert normalize_visual_policy("debug") == "record"
    assert normalize_visual_policy("strict") == "error"
    with pytest.raises(ValueError):
        normalize_visual_policy("bad")
    assert visual_call_from_call_chain("plotshape") == "plotshape"
    assert visual_call_from_call_chain("line.new") is None
    assert (
        frontend_diagnostic_visual_call(
            {"code": "P2A1507", "message": "Builtin bgcolor not lowerable"}
        )
        == "bgcolor"
    )
    assert frontend_diagnostic_visual_call({"code": "X", "message": "regular error"}) is None


def test_metadata_input_helpers_cover_options_and_defaults() -> None:
    initializer = ASTNode(
        call(
            "input.string",
            [
                arg(lit("Debug", "string"), "default"),
                arg(
                    {
                        "kind": "ArrayLiteral",
                        "elements": [lit("Debug", "string"), lit("Live", "string")],
                    },
                    "options",
                ),
                arg(lit("Execution mode", "string"), "tooltip"),
                arg(lit("Core", "string"), "group"),
                arg(lit("M", "string"), "inline"),
                arg(lit(True, "bool"), "confirm"),
            ],
        )
    )
    declaration = ASTNode({"kind": "VarDeclaration", "name": "mode"})
    meta = build_input_metadata(declaration, initializer, "mode")
    assert meta["default_python"] == "Debug"
    assert meta["public"]["options"] == ["Debug", "Live"]
    assert meta["public"]["confirm"] is True
    assert _default_for_type("source") == "close"
    assert _default_for_type("unknown") == "0.0"


def test_request_metadata_helpers_and_lower_tf_capture_diagnostics() -> None:
    nested = ASTNode(
        call("request.security", [arg(lit("AAPL")), arg(lit("D")), arg(call("request.footprint"))])
    )
    assert contains_request_call(nested)
    assert contains_any_request_call(nested)

    translator = Translator(compile_profile="diagnostic", allow_invalid_ast=True)
    mutable = translator.ctx.declare_var(
        "x",
        type_ref="float",
        qualifier="series",
        declaration_kind="normal",
        is_series=True,
        is_mutable=True,
        loc=None,
    )
    safe_input = translator.ctx.declare_var(
        "len",
        type_ref="int",
        qualifier="input",
        declaration_kind="input",
        is_series=False,
        is_mutable=False,
        loc=None,
    )
    assert is_lower_tf_safe_immutable_scalar_capture(safe_input)
    assert not is_lower_tf_safe_immutable_scalar_capture(mutable)

    diagnose_request_security_lower_tf_safety(translator, ASTNode(ident("x")))
    assert translator.ctx.diagnostics[-1].code == REQUEST_SECURITY_CAPTURE_UNSAFE

    compat = type("Compat", (), {"ctx": TranslationContext()})()
    diagnose_request_security_captures(compat, nested)
    assert compat.ctx.diagnostics[-1].severity is Severity.WARNING


def test_type_inference_branch_matrix() -> None:
    translator = Translator(compile_profile="diagnostic", allow_invalid_ast=True)
    translator.ctx.declare_var(
        "arr",
        type_ref="array",
        qualifier="series",
        declaration_kind="normal",
        is_series=True,
        is_mutable=True,
        loc=None,
    )
    cases = {
        "literal_na": (lit(None, "na"), "object"),
        "builtin_time": (ident("time"), "int"),
        "derived": (ident("hlc3"), "float"),
        "bar_index": (ident("bar_index"), "int"),
        "color_const": (member("color", "aqua"), "color"),
        "plot_style": (member("plot", "style_line"), "string"),
        "math_series": (call("math.sqrt", [arg(ident("close"))]), "float"),
        "math_int": (call("math.min", [arg(lit(1)), arg(lit(2))]), "int"),
        "str_bool": (call("str.contains", [arg(lit("abc")), arg(lit("a"))]), "bool"),
        "request": (call("request.economic", [arg(lit("US")), arg(lit("GDP"))]), "float"),
        "array_get": (call("array.get", [arg(ident("arr")), arg(lit(0))]), "float"),
        "history": ({"kind": "HistoryRefExpr", "base": ident("close"), "offset": lit(1)}, "float"),
        "conditional": (
            {
                "kind": "ConditionalExpr",
                "condition": ident("bar_index"),
                "then": lit(1),
                "else": lit(2.0),
            },
            "float",
        ),
        "tuple": ({"kind": "TupleExpr", "elements": [lit(1), lit(2.0)]}, "tuple"),
        "nz": (call("nz", [arg(ident("close"))]), "float"),
    }
    for name, (node, expected) in cases.items():
        assert translator._infer_type_info(ASTNode(node)).base_type == expected, name


def test_complex_statement_and_expression_lowering_paths() -> None:
    p = program(
        [
            var("x", lit(0), mode="var", type_name="int"),
            {
                "kind": "IfStructure",
                "condition": {
                    "kind": "BinaryExpr",
                    "op": ">",
                    "left": ident("close"),
                    "right": ident("open"),
                },
                "then_block": {
                    "kind": "Block",
                    "statements": [
                        {"kind": "Reassignment", "op": ":=", "target": ident("x"), "value": lit(1)}
                    ],
                },
                "else_if_branches": [
                    {
                        "kind": "ElseIfBranch",
                        "condition": {
                            "kind": "BinaryExpr",
                            "op": "<",
                            "left": ident("close"),
                            "right": ident("open"),
                        },
                        "block": {
                            "kind": "Block",
                            "statements": [
                                {
                                    "kind": "Reassignment",
                                    "op": ":=",
                                    "target": ident("x"),
                                    "value": lit(2),
                                }
                            ],
                        },
                    }
                ],
                "else_block": {
                    "kind": "Block",
                    "statements": [
                        {"kind": "Reassignment", "op": ":=", "target": ident("x"), "value": lit(3)}
                    ],
                },
            },
            {
                "kind": "ForRangeStructure",
                "variable": "i",
                "start": lit(0),
                "end": lit(3),
                "step": lit(1),
                "body": {"kind": "Block", "statements": [{"kind": "ContinueStatement"}]},
            },
            {
                "kind": "WhileStatement",
                "condition": {
                    "kind": "BinaryExpr",
                    "op": "<",
                    "left": ident("x"),
                    "right": lit(10),
                },
                "body": {"kind": "Block", "statements": [{"kind": "BreakStatement"}]},
            },
            var(
                "sw",
                {
                    "kind": "SwitchStructure",
                    "expression": ident("x"),
                    "branches": [
                        {
                            "kind": "SwitchCase",
                            "condition": lit(1),
                            "expression": lit("one", "string"),
                        },
                        {
                            "kind": "SwitchCase",
                            "default": True,
                            "expression": lit("other", "string"),
                        },
                    ],
                },
            ),
        ]
    )
    result = translate(p, module_name="statement_matrix")
    assert "elif pine_bool" in result.code
    assert "for i in pine_range(0, 3, 1):" in result.code
    assert "while pine_bool" in result.code
    assert "continue" in result.code
    assert "break" in result.code
    assert '"one" if' in result.code or "'one' if" in result.code
    compile(result.code, "statement_matrix.py", "exec")


def test_cli_quality_release_and_distribution_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = build_parser()
    args = parser.parse_args(["translate", "in.json", "-o", "out", "--visual-policy", "record"])
    assert args.visual_policy == "record"

    ast_path = tmp_path / "basic.ast.json"
    ast_path.write_text(
        json.dumps(program(stmt(call("plot", [arg(ident("close"))])))), encoding="utf-8"
    )
    output = tmp_path / "out"
    assert cli_main(["validate", str(ast_path)]) == 0
    assert cli_main(["translate", str(ast_path), "-o", str(output), "--visual-policy", "drop"]) == 0
    assert (output / "basic.ast.py").exists()
    assert cli_main(["coverage", str(ast_path)]) == 0
    assert cli_main(["lowering-matrix", "validate"]) == 0
    assert cli_main(["source-map-contract", "validate"]) == 0
    capsys.readouterr()

    small_pkg = tmp_path / "pkg"
    small_pkg.mkdir()
    (small_pkg / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    assert architecture_report(small_pkg, max_lines=10).oversized_count == 0
    assert duplicate_report(small_pkg).duplicate_group_count == 0
    assert release_report(Path.cwd()).ok


def test_scheduler_protocol_and_facade_modules_cover_release_surfaces() -> None:
    from ast2python.emitter import CodeEmitter
    from ast2python.emitters.code_emitter import CodeEmitter as FacadeCodeEmitter
    from ast2python.emitters.imports import ImportManager
    from ast2python.runtime_contract.interfaces import GeneratedModule
    from ast2python.scheduler import ScheduleEntry, Scheduler
    from ast2python.translator_protocols import TranslatorMixinProtocol

    ctx = TranslationContext()
    emitter = CodeEmitter(ctx.source_map)
    scheduler = Scheduler(ctx, emitter)
    scheduler.add_entry(ScheduleEntry(kind="calc", name="b", priority=1))
    scheduler.add_entry(ScheduleEntry(kind="init", name="a", priority=10))
    scheduler.add_entry(ScheduleEntry(kind="visual", name="plot", dependencies=["b"]))
    scheduler.add_entry(ScheduleEntry(kind="strategy", name="entry"))
    scheduler.emit_schedule()
    rendered = emitter.render()
    assert "# --- Init phase ---" in rendered
    assert "# calc: b" in rendered
    assert "# visual: plot" in rendered
    assert "# strategy: entry" in rendered
    assert FacadeCodeEmitter is CodeEmitter
    assert ImportManager.__name__ == "ImportManager"
    assert GeneratedModule is not None
    assert TranslatorMixinProtocol is not None


def bin_expr(op: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "BinaryExpr", "op": op, "left": left, "right": right}


def unary(op: str, operand: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "UnaryExpr", "op": op, "operand": operand}


def block(statements: list[dict[str, Any]]) -> dict[str, Any]:
    return {"kind": "Block", "statements": statements}


def test_expression_lowering_branch_matrix_and_errors() -> None:
    translator = Translator(compile_profile="diagnostic", allow_invalid_ast=True)
    translator.ctx.declare_var(
        "x",
        type_ref="float",
        qualifier="series",
        declaration_kind="normal",
        is_series=True,
        is_mutable=True,
        loc=None,
    )
    translator.ctx.declare_var(
        "arr",
        type_ref="array",
        qualifier="series",
        declaration_kind="normal",
        is_series=True,
        is_mutable=True,
        loc=None,
    ).type_info = translator._infer_type_info(
        ASTNode({"kind": "CallExpr", "callee": member("array", "new_float")})
    )

    expressions = {
        "string_eq": bin_expr("==", lit("a", "string"), lit("b", "string")),
        "modulo": bin_expr("%", lit(5), lit(2)),
        "and_op": bin_expr("and", ident("close"), ident("open")),
        "or_op": bin_expr("or", ident("close"), ident("open")),
        "unary_not": unary("not", ident("close")),
        "unary_minus": unary("-", lit(1)),
        "unary_plus": unary("+", lit(1)),
        "conditional": {
            "kind": "ConditionalExpr",
            "condition": ident("close"),
            "then": lit(1),
            "else": lit(0),
        },
        "tuple": {"kind": "TupleExpr", "elements": [lit(1), lit(2)]},
        "array_literal": {"kind": "ArrayLiteral", "elements": [lit(1), lit(2)]},
        "map_literal": {
            "kind": "MapLiteral",
            "entries": [{"kind": "MapEntry", "key": lit("k", "string"), "value": lit(1)}],
        },
        "identifier_group": ident("group"),
        "identifier_hl2": ident("hl2"),
        "identifier_hlc3": ident("hlc3"),
        "identifier_ohlc4": ident("ohlc4"),
        "identifier_hlcc4": ident("hlcc4"),
        "identifier_time_component": ident("year"),
        "member_syminfo": member("syminfo", "ticker"),
        "member_timeframe": member("timeframe", "isdaily"),
        "member_barstate": member("barstate", "isconfirmed"),
        "member_strategy_direction": {
            "kind": "MemberAccessExpr",
            "object": member("strategy", "direction"),
            "member": "long",
        },
        "member_strategy_commission": {
            "kind": "MemberAccessExpr",
            "object": member("strategy", "commission"),
            "member": "percent",
        },
        "member_strategy_readonly": member("strategy", "equity"),
        "member_barmerge": member("barmerge", "lookahead_on"),
        "member_display": member("display", "all"),
        "member_extend": member("extend", "right"),
        "member_color": member("color", "red"),
        "member_array": member("array", "get"),
        "member_map": member("map", "get"),
        "member_matrix": member("matrix", "get"),
        "member_request": member("request", "security"),
        "member_ta_derived": member("ta", "hl2"),
        "member_ta_atr": member("ta", "atr20"),
        "member_math": member("math", "sqrt"),
        "member_visual": member("line", "set_xy1"),
        "history_builtin": {"kind": "HistoryRefExpr", "base": ident("close"), "offset": lit(1)},
        "history_time_component": {
            "kind": "HistoryRefExpr",
            "base": ident("year"),
            "offset": lit(1),
        },
        "history_derived": {"kind": "HistoryRefExpr", "base": ident("hlc3"), "offset": lit(1)},
        "history_series_var": {"kind": "HistoryRefExpr", "base": ident("x"), "offset": lit(1)},
    }
    rendered = {
        name: translator.translate_expression(ASTNode(expression))
        for name, expression in expressions.items()
    }
    assert rendered["modulo"] == "(5 % 2)"
    assert "pine_bool" in rendered["and_op"]
    assert "PineArray" in rendered["array_literal"]
    assert "PineMap" in rendered["map_literal"]
    assert rendered["identifier_group"] == '""'
    assert "hl2_series" in rendered["member_ta_derived"]
    assert "atr(" in rendered["member_ta_atr"]
    assert rendered["history_builtin"].startswith("self.rt.close[")
    assert "expr_history" in rendered["history_time_component"]

    for bad in [
        bin_expr("**", lit(1), lit(2)),
        unary("~", lit(1)),
        {"kind": "MatrixLiteral"},
        {"kind": "UnknownExpr"},
        {"kind": "HistoryRefExpr", "base": lit(1), "offset": lit(1)},
        {"kind": "HistoryRefExpr", "base": ident("close")},
    ]:
        with pytest.raises((UnsupportedNodeError, TypeResolutionError)):
            translator.translate_expression(ASTNode(bad))


def test_statement_helpers_cover_local_tuple_import_for_in_and_switch_paths() -> None:
    translator = Translator(
        compile_profile="diagnostic",
        allow_invalid_ast=True,
        allow_external_library_stubs=True,
    )
    translator.ctx.enter_scope("function")
    translator.ctx.declare_var(
        "local",
        type_ref="float",
        qualifier="simple",
        declaration_kind="normal",
        is_series=False,
        is_mutable=True,
        loc=None,
        prefer_py_name="local",
    )
    translator._emit_reassignment(
        ASTNode({"kind": "Reassignment", "op": "+=", "target": ident("local"), "value": lit(2)})
    )
    translator._emit_var_declaration(ASTNode(var("once", lit(1), mode="varip")))
    translator.ctx.exit_scope()

    translator._record_import_alias(
        ASTNode(
            {
                "kind": "ImportDeclaration",
                "alias": "lib",
                "path": "owner/lib/1",
                "owner": "owner",
                "library": "lib",
                "version": 1,
            }
        )
    )
    assert "lib" in translator.ctx.import_aliases
    assert "local = pine_add" in translator.emitter.render()

    rejected = Translator(compile_profile="diagnostic", allow_invalid_ast=True)
    with pytest.raises(UnsupportedBuiltinError):
        rejected._record_import_alias(
            ASTNode({"kind": "ImportDeclaration", "alias": "lib", "path": "owner/lib/1"})
        )

    tuple_decl = ASTNode(
        {
            "kind": "TupleDeclaration",
            "targets": [
                {"kind": "Identifier", "name": "fast"},
                {"kind": "Discard"},
                {"kind": "TupleTarget", "name": "slow"},
            ],
            "initializer": call(
                "ta.macd", [arg(ident("close")), arg(lit(12)), arg(lit(26)), arg(lit(9))]
            ),
        }
    )
    translator._emit_tuple_declaration(tuple_decl)
    assert "_discard_2" in translator.emitter.render()
    with pytest.raises(UnsupportedNodeError):
        translator._tuple_targets(ASTNode({"kind": "TupleDeclaration", "targets": "bad"}))
    with pytest.raises(UnsupportedNodeError):
        translator._tuple_targets(
            ASTNode({"kind": "TupleDeclaration", "targets": [{"kind": "BadTarget"}]})
        )

    for_in_nodes = [
        {"kind": "ForInStructure", "names": ["k", "v"], "iterable": ident("fast")},
        {"kind": "ForInStructure", "names": "item", "iterable": ident("fast")},
        {"kind": "ForInStructure", "target": ident("only"), "iterable": ident("fast")},
    ]
    for raw in for_in_nodes:
        translator._emit_for_in(ASTNode(raw))
    with pytest.raises(UnsupportedNodeError):
        translator._for_in_target_names(ASTNode({"kind": "ForInStructure", "target": lit(1)}))

    translator._emit_switch(
        ASTNode(
            {
                "kind": "SwitchStructure",
                "branches": [
                    {
                        "kind": "SwitchCase",
                        "condition": ident("fast"),
                        "body": block([stmt(lit(1))]),
                    },
                    {"kind": "SwitchCase", "default": True},
                ],
            }
        )
    )
    translator._emit_switch(ASTNode({"kind": "SwitchStructure", "cases": []}))
    translator._emit_while(ASTNode({"kind": "WhileStatement", "condition": ident("fast")}))
    rendered = translator.emitter.render()
    assert "for (k, v) in" in rendered
    assert "else:" in rendered
    assert "while pine_bool" in rendered

    with pytest.raises(UnsupportedNodeError):
        translator._emit_while(ASTNode({"kind": "WhileStatement"}))
    with pytest.raises(UnsupportedNodeError):
        translator._emit_if(ASTNode({"kind": "IfStructure", "then_block": block([])}))
    with pytest.raises(UnsupportedNodeError):
        translator._emit_for_range(ASTNode({"kind": "ForRangeStructure", "variable": "i"}))


def test_call_lowering_request_reference_strategy_and_external_paths() -> None:
    translator = Translator(
        compile_profile="diagnostic",
        allow_invalid_ast=True,
        allow_unsupported_request_stubs=True,
        allow_external_library_stubs=True,
        visual_policy="record",
    )
    translator.ctx.import_aliases["lib"] = {"path": "owner/lib/1"}
    translator.ctx.declare_var(
        "arr",
        type_ref="array",
        qualifier="series",
        declaration_kind="normal",
        is_series=True,
        is_mutable=True,
        loc=None,
    )

    calls = {
        "na": {"kind": "CallExpr", "callee": lit(None, "na"), "arguments": [arg(ident("close"))]},
        "request_security": call(
            "request.security",
            [arg(lit("AAPL", "string")), arg(lit("D", "string")), arg(ident("close"))],
        ),
        "request_lower_tf": call(
            "request.security_lower_tf",
            [arg(lit("AAPL", "string")), arg(lit("5", "string")), arg(ident("close"))],
        ),
        "footprint": call("request.footprint", [arg(lit("AAPL", "string"))]),
        "unsupported_request_stub": call("request.financial", [arg(lit("AAPL", "string"))]),
        "external_library": call("lib.foo", [arg(lit(1)), arg(lit(2), "bar")]),
        "color_new": call("color.new", [arg(member("color", "red")), arg(lit(20))]),
        "array_from": call("array.from", [arg(lit(1)), arg(lit(2))]),
        "array_new": call("array.new", [arg(lit(3))]),
        "array_get": call("array.get", [arg(ident("arr")), arg(lit(0))]),
        "map_new": call("map.new", []),
        "matrix_new": call("matrix.new", [arg(lit(2)), arg(lit(2)), arg(lit(0.0))]),
        "strategy_readonly": call("strategy.closedtrades.entry_id", [arg(lit(0))]),
        "strategy_risk": call(
            "strategy.risk.allow_entry_in", [arg(member("strategy", "direction"))]
        ),
        "strategy_entry": call(
            "strategy.entry", [arg(lit("L", "string")), arg(member("strategy", "long"))]
        ),
        "plot_record": call("plot", [arg(ident("close")), arg(lit("Close", "string"))]),
        "plotshape_general": call(
            "plotshape", [arg(ident("close")), arg(lit("Shape", "string"), "title")]
        ),
        "ta_dmi": call("ta.dmi", [arg(lit(14)), arg(lit(14))]),
        "ta_sar": call("ta.sar", [arg(lit(0.02)), arg(lit(0.02)), arg(lit(0.2))]),
        "ta_tr": call("ta.tr", []),
        "math": call("math.sqrt", [arg(lit(4.0))]),
        "str": call("str.tostring", [arg(lit(1))]),
    }
    rendered = {name: translator.translate_expression(ASTNode(raw)) for name, raw in calls.items()}
    assert "request_security" in rendered["request_security"]
    assert "expression_hint" in rendered["request_lower_tf"]
    assert rendered["unsupported_request_stub"] == "na"
    assert "_external_library_call" in rendered["external_library"]
    assert "PineArray" in rendered["array_from"]
    assert "PineMap" in rendered["map_new"]
    assert "self.ctx.closedtrades_entry_id" in rendered["strategy_readonly"]
    assert "risk_allow_entry_in" in rendered["strategy_risk"]
    assert "plot_recorder.record_plot" in rendered["plot_record"]
    assert "_visual_call" in rendered["plotshape_general"]
    assert "runtime=self.rt" in rendered["ta_dmi"]
    assert "high.current" in rendered["ta_sar"]
    assert rendered["ta_tr"].startswith("tr(")
    assert "pine_string.tostring" in rendered["str"]

    bool_arg = ASTNode(call("na", [arg(lit(True, "bool"))]))
    with pytest.raises(TypeResolutionError):
        translator._translate_na_helper_call("na", bool_arg, runtime_expr="self.rt")
    with pytest.raises(UnsupportedBuiltinError):
        Translator(
            compile_profile="diagnostic", allow_invalid_ast=True
        )._translate_unsupported_request_call(
            "request.financial", ASTNode(call("request.financial")), runtime_expr="self.rt"
        )


def test_module_entrypoint_and_metadata_type_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["ast2python", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("ast2python.__main__", run_name="__main__")
    assert exc_info.value.code == 0

    translator = Translator(compile_profile="diagnostic", allow_invalid_ast=True)
    assert infer_dtype(translator, ASTNode(lit(1.0))) == "float"
    assert _type_ref_name(ASTNode({"kind": "VarDeclaration"})) is None
    assert (
        _type_ref_name(
            ASTNode({"kind": "VarDeclaration", "type_ref": {"kind": "TypeRef", "name": "float"}})
        )
        == "float"
    )
