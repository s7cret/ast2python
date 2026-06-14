from __future__ import annotations

import csv
import json
import sys
import types
from pathlib import Path

import pytest

from ast2python.arg_helper import call_arguments, ordered_call_arguments
from ast2python.ast.schema import (
    ASTNode,
    ensure_program_node,
    load_ast,
    normalized_program_dict,
    validate_ast,
)
from ast2python.binder import bind_builtin_call, type_matches
from ast2python.binder_model import TypeInfo
from ast2python.call_dispatch import dispatch_call, dispatch_fallback_call
from ast2python.call_handlers_common import (
    alert,
    alertcondition,
    color_new,
    fixnan,
    input_runtime,
    na,
    nz,
)
from ast2python.call_handlers_strategy import builtin_strategy_prefix, strategy_long, strategy_short
from ast2python.call_handlers_time import (
    builtin_time_close_exact,
    builtin_time_exact,
    make_date_helper,
    timeframe_change_exact,
    timestamp,
)
from ast2python.cli.commands import (
    _load_bars,
    _load_generated_class,
    command_coverage,
    command_lowering_matrix,
    command_smoke,
    command_source_map_contract,
    command_translate,
    command_translate_many,
    command_validate,
)
from ast2python.cli.main import main as cli_main
from ast2python.diagnostics import Diagnostic, Severity, SourceLocation
from ast2python.distribution import build_zip, distribution_manifest
from ast2python.distribution import main as distribution_main
from ast2python.emitters.time import PineTimeEmitter, _timezone_for_name
from ast2python.errors import (
    AST2PythonError,
    TypeResolutionError,
    UnsupportedBuiltinError,
    UnsupportedNodeError,
    ValidationError,
)
from ast2python.imports import ImportManager
from ast2python.lowering_matrix import (
    export_lowering_matrix_markdown,
    export_source_map_contract_markdown,
)
from ast2python.lowering_matrix.loader import load_lowering_matrix
from ast2python.lowering_matrix.validate import (
    LoweringMatrixError,
    validate_lowering_matrix_payload,
    validate_source_map_contract_payload,
)
from ast2python.lowering_matrix.validate import (
    main as lowering_validate_main,
)
from ast2python.naming import NamingRegistry, snake_case
from ast2python.profiles import CompileProfile
from ast2python.quality import architecture_report, duplicate_report
from ast2python.quality import main as quality_main
from ast2python.release import main as release_main
from ast2python.release import release_report
from ast2python.runtime_contract.generated_base import GeneratedIndicatorBase
from ast2python.translator import Translator, translate_ast
from ast2python.translator_mixins.metadata_declarations import (
    call_arguments as declaration_call_arguments,
)
from ast2python.translator_mixins.metadata_declarations import (
    collect_declaration_metadata,
    extract_declaration_title,
    literal_or_rendered,
    strategy_context_kwargs,
)
from ast2python.translator_mixins.type_inference import infer_type_info
from ast2python.translator_support import member_chain
from ast2python.types import join_qualifiers, make_type_info
from ast2python.visuals import (
    frontend_diagnostic_visual_call,
    normalize_visual_policy,
    visual_call_from_call_chain,
)
from tests.contract_metadata import with_valid_producer_metadata


def ident(name: str) -> dict[str, object]:
    return {"kind": "Identifier", "name": name}


def lit(value: object, literal_type: str = "int") -> dict[str, object]:
    return {"kind": "Literal", "literal_type": literal_type, "value": value}


def arg(value: dict[str, object], name: str | None = None) -> dict[str, object]:
    return {"kind": "Argument", "name": name, "value": value}


def call(
    callee: dict[str, object] | str, args: list[dict[str, object]] | None = None
) -> dict[str, object]:
    raw_callee = ident(callee) if isinstance(callee, str) else callee
    return {"kind": "CallExpr", "callee": raw_callee, "arguments": args or []}


def member(
    obj: str | dict[str, object], name: str, *, kind: str = "MemberAccessExpr"
) -> dict[str, object]:
    return {"kind": kind, "object": ident(obj) if isinstance(obj, str) else obj, "member": name}


def program(
    items: list[dict[str, object]] | None = None, *, script_type: str = "indicator"
) -> dict[str, object]:
    return with_valid_producer_metadata(
        {
            "kind": "Program",
            "language": "pine",
            "version": 6,
            "declaration": {
                "kind": "DeclarationStatement",
                "script_type": script_type,
                "call": call(script_type, [arg(lit("Polish", "string"))]),
            },
            "items": items or [],
        }
    )


def test_argument_helpers_error_and_named_ordering() -> None:
    with pytest.raises(UnsupportedNodeError):
        call_arguments(ASTNode(call("math.sqrt", [{"kind": "Argument", "name": None}])))
    node = ASTNode(
        call(
            "math.max",
            [arg(lit(10), "number2"), arg(lit(20)), arg(lit(30), "extra")],
        )
    )
    ordered = ordered_call_arguments("math.max", node)
    assert [name for name, _ in ordered] == ["number2", None, "extra"]


def test_ast_schema_unwrap_locations_and_validation(tmp_path: Path) -> None:
    span_node = ASTNode({"kind": "Identifier", "name": "x", "span": {"line": 1, "column": 2}})
    assert span_node.loc is not None and span_node.loc.line == 1
    legacy = ASTNode({"type": "Identifier", "loc": {"start_line": 3, "start_col": 4}})
    assert legacy.kind == "Identifier" and legacy.loc is not None and legacy.loc.column == 4
    p = program()
    wrapped = ensure_program_node({"ast": p, "metadata": {"producer": "x"}})
    assert wrapped.kind == "Program"
    wrapped_result = ensure_program_node({"result": {"program": p, "metadata": {"producer": "x"}}})
    assert wrapped_result.kind == "Program"
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"program": p}), encoding="utf-8")
    assert load_ast(path).kind == "Program"
    assert normalized_program_dict({"program": p})["kind"] == "Program"
    assert validate_ast(ensure_program_node({**p, "language": "other"}))
    with pytest.raises(ValidationError):
        ensure_program_node([])  # type: ignore[arg-type]


def test_binder_edge_cases() -> None:
    assert type_matches("object", frozenset({"object"}))
    assert type_matches("line", frozenset({"PineObjectId"}))
    assert type_matches("PineArray", frozenset({"array"}))
    assert type_matches("int", frozenset({"float"}))
    assert bind_builtin_call("missing.builtin", [])
    simple_obj = TypeInfo("object", "simple", origin="untyped_param")
    assert bind_builtin_call("math.sqrt", [(None, simple_obj)]) == []
    assert bind_builtin_call("ta.ema", [(None, simple_obj), (None, simple_obj)]) == []
    assert bind_builtin_call(
        "math.sqrt",
        [("number", TypeInfo("float", "const")), ("number", TypeInfo("float", "const"))],
    )
    assert bind_builtin_call("math.sqrt", [("unknown", TypeInfo("float", "const"))])
    assert bind_builtin_call(
        "ta.adx", [(None, TypeInfo("int", "simple")), (None, TypeInfo("int", "simple"))]
    )


def test_call_dispatch_fallbacks_and_visuals() -> None:
    t_drop = Translator(compile_profile="diagnostic", visual_policy="drop")
    assert (
        dispatch_fallback_call(
            t_drop,
            "plot",
            ASTNode(call("plot", [arg(ident("close"))])),
            ASTNode(ident("plot")),
            runtime_expr="self.rt",
        )
        == "None"
    )
    with pytest.raises(AST2PythonError):
        dispatch_fallback_call(
            Translator(compile_profile="diagnostic", visual_policy="error"),
            "plot",
            ASTNode(call("plot", [arg(ident("close"))])),
            ASTNode(ident("plot")),
            runtime_expr="self.rt",
        )


def test_cli_commands_and_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ast_path = tmp_path / "in.json"
    ast_path.write_text(json.dumps(program()), encoding="utf-8")
    assert command_validate(str(ast_path)) == 0
    assert (
        command_translate(
            str(ast_path),
            str(tmp_path / "out"),
            module_name="m",
            strict=False,
            emit_source_comments=True,
        )
        == 0
    )
    assert (
        command_translate_many(
            [str(ast_path)], str(tmp_path / "many"), strict=False, emit_source_comments=True
        )
        == 0
    )
    assert command_coverage(str(ast_path), strict=False) == 0
    assert cli_main(["validate", str(ast_path)]) == 0
    assert cli_main(["coverage", str(ast_path)]) == 0
    assert cli_main(["lowering-matrix", "validate"]) == 0
    assert cli_main(["source-map-contract", "validate"]) == 0
    assert command_lowering_matrix("validate", output=str(tmp_path / "m.md")) == 0
    assert command_lowering_matrix("export-md", output=str(tmp_path / "m.md")) == 0
    assert command_source_map_contract("validate", output=str(tmp_path / "s.md")) == 0
    assert command_source_map_contract("export-md", output=str(tmp_path / "s.md")) == 0
    assert (tmp_path / "m.md").exists()
    assert (tmp_path / "s.md").exists()
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(
        json.dumps({"kind": "Program", "language": "pine", "items": []}), encoding="utf-8"
    )
    assert command_validate(str(bad_path)) == 1
    captured = capsys.readouterr()
    assert "nodes_total" in captured.out


def test_cli_many_error_and_coverage_non_strict(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"kind": "Program", "language": "pine", "declaration": None}), encoding="utf-8"
    )
    assert (
        command_translate_many(
            [str(bad)],
            str(tmp_path / "out"),
            strict=False,
            emit_source_comments=True,
            compile_profile="diagnostic",
            allow_invalid_ast=True,
        )
        == 1
    )


def test_smoke_command_runtime_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generated = tmp_path / "generated.py"
    generated.write_text(
        "class GeneratedIndicator:\n"
        "    def __init__(self, params=None, runtime=None): self.params=params; self.runtime=runtime\n"
        "    def run(self, bars): return list(bars)\n",
        encoding="utf-8",
    )
    assert command_smoke(str(generated)) == 0

    core = types.ModuleType("pinelib.core")

    class Bar:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class SymbolInfo:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class TimeframeInfo:
        @classmethod
        def from_string(cls, value: str) -> TimeframeInfo:
            return cls()

    class Visual:
        pass

    class PineRuntime:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)
            self.visual = Visual()

    core.Bar = Bar
    core.PineRuntime = PineRuntime
    core.SymbolInfo = SymbolInfo
    core.TimeframeInfo = TimeframeInfo
    pinelib = types.ModuleType("pinelib")
    monkeypatch.setitem(sys.modules, "pinelib", pinelib)
    monkeypatch.setitem(sys.modules, "pinelib.core", core)
    assert command_smoke(str(generated)) == 0
    csv_path = tmp_path / "bars.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["time", "open", "high", "low", "close", "volume", "time_close"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "time": "1",
                "open": "1",
                "high": "2",
                "low": "0",
                "close": "1",
                "volume": "3",
                "time_close": "2",
            }
        )
    assert len(_load_bars(str(csv_path))) == 1
    json_path = tmp_path / "bars.json"
    json_path.write_text(
        json.dumps([{"time": 1, "open": 1, "high": 2, "low": 0, "close": 1, "volume": 3}]),
        encoding="utf-8",
    )
    assert len(_load_bars(str(json_path))) == 1
    assert _load_generated_class(generated).__name__ == "GeneratedIndicator"
    missing = tmp_path / "missing_class.py"
    missing.write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        _load_generated_class(missing)


def test_distribution_release_quality_and_matrix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    (root / "ast2python").mkdir(parents=True)
    (root / "ast2python" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "docs").mkdir()
    for doc in [
        "README.md",
        "ARCHITECTURE.md",
        "COMPATIBILITY.md",
        "DEVELOPMENT.md",
        "OPENPINE_PIPELINE.md",
        "RELEASE_4_0.md",
        "SECURITY.md",
    ]:
        (root / "docs" / doc).write_text("x", encoding="utf-8")
    (root / "RELEASE_MANIFEST_v4.0.0.json").write_text("{}", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build" / "x.pyc").write_bytes(b"x")
    manifest = distribution_manifest(root)
    assert manifest.hygiene_ok
    digest = build_zip(root, tmp_path / "out.zip")
    assert len(digest) == 64
    assert distribution_main(["manifest", "--root", str(root)]) == 0
    assert (
        distribution_main(
            ["build-zip", "--root", str(root), "--output", str(tmp_path / "out2.zip")]
        )
        == 0
    )
    assert release_report(root).ok
    assert release_main(["--root", str(root), "--json", str(tmp_path / "release.json")]) == 0
    assert quality_main(["duplicates", str(root / "ast2python")]) == 0
    assert quality_main(["architecture", str(root / "ast2python"), "--max-lines", "1"]) == 1
    assert architecture_report(root / "ast2python", max_lines=1).oversized_count == 1
    assert duplicate_report(root / "ast2python").duplicate_group_count == 0
    lm_path = export_lowering_matrix_markdown(str(tmp_path / "lm.md"))
    assert "AST kind" in lm_path.read_text(encoding="utf-8")
    sm_path = export_source_map_contract_markdown(str(tmp_path / "sm.md"))
    assert "Source Map" in sm_path.read_text(encoding="utf-8")
    assert lowering_validate_main([]) == 0
    with pytest.raises(LoweringMatrixError):
        validate_lowering_matrix_payload(
            {"schema_version": "bad", "runtime_contract": "bad", "entries": []}
        )
    with pytest.raises(LoweringMatrixError):
        validate_lowering_matrix_payload(
            {
                "schema_version": "pine.ast2python.lowering_matrix.v1",
                "runtime_contract": "1.4",
                "entries": ["bad"],
            }
        )
    with pytest.raises(LoweringMatrixError):
        validate_source_map_contract_payload(
            {
                "schema_version": "bad",
                "runtime_contract": "bad",
                "required_fields": "x",
                "format": "bad",
            }
        )
    with pytest.raises(LoweringMatrixError):
        validate_source_map_contract_payload(
            {
                "schema_version": "pine.ast2python.source_map_contract.v1",
                "runtime_contract": "1.4",
                "required_fields": [],
                "format": "json-array",
            }
        )
    assert load_lowering_matrix()["runtime_contract"] == "1.4"
    with pytest.raises(SystemExit):
        distribution_main(["unknown"])
    assert quality_main(["architecture", str(root / "missing")]) == 0
    capsys.readouterr()


def test_emitters_imports_profiles_and_misc() -> None:
    registry = ImportManager()
    assert registry.require_from("pinelib", "ta", alias="pine_ta") == "pine_ta"
    assert registry.require_from("pinelib", "ta", alias="pine_ta") == "pine_ta"
    assert "from pinelib import ta as pine_ta" in registry.render()
    naming = NamingRegistry()
    assert naming.reserve("class") == "class_"
    assert naming.reserve("Hello world") == "hello_world"
    assert snake_case("9 Lives") == "n_9_lives"
    assert CompileProfile.from_options("diagnostic", allow_invalid_ast=True).allow_invalid_ast
    with pytest.raises(ValueError):
        CompileProfile.from_options("production", allow_invalid_ast=True)
    assert join_qualifiers("const", "series") == "series"
    assert make_type_info("float", "series").qualifier == "series"
    assert SourceLocation(line=1, column=2).source_map == "L1"
    assert (
        Diagnostic("W", "msg", Severity.WARNING, SourceLocation(line=1)).to_dict()["severity"]
        == "warning"
    )
    assert normalize_visual_policy("recorder") == "record"
    assert normalize_visual_policy("drop") == "drop"
    assert visual_call_from_call_chain("plot") == "plot"
    assert (
        frontend_diagnostic_visual_call({"code": "P2A1507", "message": "Builtin plot unsupported"})
        == "plot"
    )
    with pytest.raises(ValueError):
        normalize_visual_policy("bad")


class _DummyBase(GeneratedIndicatorBase):
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def _process_bar(self, bar: object) -> None:
        self.items.append({"bar": bar})

    def run(self, bars: object) -> list[dict[str, object]]:
        for bar in bars:  # type: ignore[union-attr]
            self._process_bar(bar)
        return self.items


def test_generated_base_runtime() -> None:
    base = _DummyBase()
    assert base.run([1, 2]) == [{"bar": 1}, {"bar": 2}]


def test_type_inference_matrix() -> None:
    tr = Translator(compile_profile="diagnostic")
    tr.ctx.declare_var(
        "inp",
        type_ref="int",
        qualifier="input",
        declaration_kind="input",
        is_series=True,
        is_mutable=False,
        loc=None,
        prefer_py_name="inp",
    )
    info_objna = tr.ctx.declare_var(
        "objna",
        type_ref="float",
        qualifier="series",
        declaration_kind="normal",
        is_series=True,
        is_mutable=True,
        loc=None,
        prefer_py_name="objna",
    )
    info_objna.type_info = make_type_info("object", "const")
    info_ln = tr.ctx.declare_var(
        "ln",
        type_ref="line",
        qualifier="series",
        declaration_kind="normal",
        is_series=True,
        is_mutable=True,
        loc=None,
        prefer_py_name="ln",
    )
    info_ln.type_info = make_type_info("object", "series")
    cases = [
        (None, "object", "simple"),
        (lit(None, "na"), "object", "const"),
        (ident("close"), "float", "series"),
        (ident("hlc3"), "float", "series"),
        (ident("bar_index"), "int", "series"),
        (ident("na"), "object", "const"),
        (ident("missing"), "object", "simple"),
        (ident("inp"), "int", "input"),
        (ident("objna"), "float", "series"),
        (ident("ln"), "PineObjectId", "series"),
        (member("strategy", "long"), "string", "const"),
        (member("strategy", "opentrades"), "int", "series"),
        (member("strategy", "netprofit"), "float", "series"),
        (member("syminfo", "mintick"), "float", "simple"),
        (member("syminfo", "ticker"), "string", "simple"),
        (member("barmerge", "lookahead_on"), "string", "const"),
        (member("color", "red"), "color", "const"),
        (member("ta", "hlc3"), "float", "series"),
        (
            {
                "kind": "Call",
                "callee": {"kind": "MemberAccess", "object": ident("ta"), "member": "hl2"},
                "arguments": [],
            },
            "float",
            "series",
        ),
        (call("time", [arg(lit("D", "string"))]), "int", "series"),
        (call(member("input", "timeframe"), []), "string", "input"),
        (call(member("input", "time"), [arg(lit("D", "string"))]), "int", "series"),
        ({"kind": "BinaryExpr", "op": ">", "left": lit(1), "right": lit(2)}, "bool", "const"),
        (
            {"kind": "BinaryExpr", "op": "+", "left": lit("a", "string"), "right": lit(2)},
            "string",
            "const",
        ),
        ({"kind": "UnaryExpr", "operand": lit(1)}, "int", "const"),
        (
            {
                "kind": "ConditionalExpr",
                "condition": lit(True, "bool"),
                "then": lit(1),
                "else": lit(2.0, "float"),
            },
            "float",
            "const",
        ),
        ({"kind": "TupleExpr", "items": [lit(1), lit(2.0, "float")]}, "tuple", "const"),
        ({"kind": "HistoryRefExpr", "base": ident("close"), "index": lit(1)}, "float", "series"),
        (call(lit(None, "na"), [arg(ident("close"))]), "bool", "series"),
        (call(member("input", "bool"), []), "bool", "input"),
        (call(member("input", "int"), []), "int", "input"),
        (call(member("str", "tonumber"), [arg(lit("1", "string"))]), "float", "series"),
        (call(member("str", "tostring"), [arg(lit(1))]), "string", "series"),
        (
            call(member("str", "contains"), [arg(lit("a", "string")), arg(lit("a", "string"))]),
            "bool",
            "series",
        ),
        (call(member("str", "length"), [arg(lit("a", "string"))]), "int", "series"),
        (
            call(member("ta", "crossover"), [arg(ident("close")), arg(ident("open"))]),
            "bool",
            "series",
        ),
        (call(member("ta", "barssince"), [arg(ident("close"))]), "int", "series"),
        (
            call(member("ta", "bb"), [arg(ident("close")), arg(lit(20)), arg(lit(2.0, "float"))]),
            "tuple",
            "series",
        ),
        (call(member("request", "security_lower_tf"), []), "array", "series"),
        (call(member(member("strategy", "closedtrades"), "entry_id"), []), "string", "series"),
        (call(member(member("strategy", "closedtrades"), "entry_time"), []), "int", "series"),
        (call(member(member("strategy", "closedtrades"), "profit"), []), "float", "series"),
        (call(member("request", "financial"), []), "float", "series"),
        (
            call(
                member("request", "security"),
                [
                    arg(lit("A", "string")),
                    arg(lit("D", "string")),
                    arg(
                        call(
                            member("ta", "bb"),
                            [arg(ident("close")), arg(lit(20)), arg(lit(2.0, "float"))],
                        )
                    ),
                ],
            ),
            "tuple",
            "series",
        ),
        (
            call(
                member("request", "security"),
                [arg(lit("A", "string")), arg(lit("D", "string")), arg(ident("close"))],
            ),
            "float",
            "series",
        ),
        (call(member("input", "string"), []), "string", "input"),
        (call(member("input", "time"), []), "int", "input"),
        (call(member("input", "source"), []), "source", "input"),
        (call("na", [arg(ident("close"))]), "bool", "series"),
        (call("na", []), "bool", "simple"),
        (call("nz", [arg(ident("close"))]), "float", "series"),
        (call("nz", []), "float", "series"),
        (call(member("math", "min"), [arg(lit(1)), arg(lit(2))]), "int", "const"),
        (call(member("math", "sqrt"), [arg(lit(4))]), "float", "const"),
        (call("int", [arg(lit(1.2, "float"))]), "int", "const"),
        (call("float", []), "float", "series"),
        (call("bool", []), "bool", "series"),
        (call("str", []), "string", "series"),
        (call(member("line", "new"), []), "PineObjectId", "series"),
        (call(member("array", "size"), []), "int", "series"),
        (call(member("array", "get"), []), "float", "series"),
        (call(member("array", "from"), []), "array", "series"),
        (call(member("array", "copy"), []), "array", "series"),
        (call(member("matrix", "get"), []), "float", "series"),
        (call(member("map", "get"), []), "float", "series"),
        (call(member("map", "size"), []), "map", "series"),
        (
            {"kind": "VarDeclaration", "type_ref": {"kind": "TypeRef", "name": "array"}},
            "array",
            "series",
        ),
    ]
    for raw, base, qualifier in cases:
        info = infer_type_info(tr, None if raw is None else ASTNode(raw))
        assert (info.base_type, info.qualifier) == (base, qualifier), raw


def test_translation_branches_complex_program() -> None:
    prog = program(
        [
            {
                "kind": "VarDeclaration",
                "name": "x",
                "type": "float",
                "declaration_kind": "var",
                "initializer": lit(None, "na"),
            },
            {
                "kind": "VarDeclaration",
                "name": "flag",
                "type": "bool",
                "initializer": lit(True, "bool"),
            },
            {
                "kind": "TupleDeclaration",
                "targets": ["a", "b", "c"],
                "initializer": call(
                    member("ta", "macd"),
                    [arg(ident("close")), arg(lit(12)), arg(lit(26)), arg(lit(9))],
                ),
            },
            {
                "kind": "Reassignment",
                "op": ":=",
                "target": ident("x"),
                "value": {
                    "kind": "ConditionalExpr",
                    "condition": ident("flag"),
                    "then": lit(1.0, "float"),
                    "else": lit(2.0, "float"),
                },
            },
            {
                "kind": "IfStructure",
                "condition": ident("flag"),
                "then_block": {
                    "kind": "Block",
                    "statements": [
                        {
                            "kind": "AlertCondition",
                            "condition": ident("flag"),
                            "title": lit("title", "string"),
                            "message": lit("msg", "string"),
                        }
                    ],
                },
                "else_block": {
                    "kind": "Block",
                    "statements": [
                        {
                            "kind": "ExpressionStatement",
                            "expression": call("plot", [arg(ident("x"))]),
                        }
                    ],
                },
            },
            {
                "kind": "ForRangeStructure",
                "variable": "i",
                "start": lit(0),
                "end": lit(2),
                "body": {"kind": "Block", "statements": [{"kind": "ContinueStatement"}]},
            },
            {
                "kind": "WhileStructure",
                "condition": ident("flag"),
                "body": {"kind": "Block", "statements": [{"kind": "BreakStatement"}]},
            },
            {
                "kind": "SwitchStructure",
                "expression": ident("flag"),
                "cases": [
                    {
                        "kind": "SwitchCase",
                        "value": lit(True, "bool"),
                        "block": {
                            "kind": "Block",
                            "statements": [
                                {
                                    "kind": "ExpressionStatement",
                                    "expression": call("plot", [arg(ident("close"))]),
                                }
                            ],
                        },
                    }
                ],
                "default": {
                    "kind": "Block",
                    "statements": [
                        {
                            "kind": "ExpressionStatement",
                            "expression": call("plotchar", [arg(ident("flag"))]),
                        }
                    ],
                },
            },
        ]
    )
    result = translate_ast(
        prog, module_name="complex", compile_profile="diagnostic", visual_policy="drop"
    )
    assert "for i in pine_range" in result.code
    assert "while pine_bool" in result.code
    assert "if pine_bool" in result.code
    assert "alertcondition" in result.code
    compile(result.code, "complex.py", "exec")


def test_member_chain_and_stable_json() -> None:
    node = ASTNode(member(member("strategy", "closedtrades"), "entry_id"))
    assert member_chain(node) == "strategy.closedtrades.entry_id"


def test_expression_low_level_branch_matrix() -> None:
    tr = Translator(compile_profile="diagnostic", visual_policy="record")
    tr.ctx.mode = "strategy"
    tr.ctx.declare_var(
        "local",
        type_ref="float",
        qualifier=None,
        declaration_kind="normal",
        is_series=False,
        is_mutable=True,
        loc=None,
        prefer_py_name="local",
    )
    arr = tr.ctx.declare_var(
        "arr",
        type_ref="array",
        qualifier="series",
        declaration_kind="normal",
        is_series=True,
        is_mutable=True,
        loc=None,
        prefer_py_name="arr",
    )
    arr.type_info = make_type_info("array", "series")

    assert tr._is_visual_method_call("line.set_x1")
    assert not tr._is_visual_method_call("line.get_x1")
    assert (
        tr._translate_scalar_operand(ASTNode(ident("close")), runtime_expr="self.rt")
        == "self.rt.close.current"
    )
    assert "pine_eq" in tr.translate_expression(
        ASTNode({"kind": "BinaryExpr", "op": "==", "left": lit(1), "right": lit(1)})
    )
    assert (
        tr.translate_expression(
            ASTNode({"kind": "BinaryExpr", "op": "%", "left": lit(5), "right": lit(2)})
        )
        == "(5 % 2)"
    )
    assert "and" in tr.translate_expression(
        ASTNode(
            {
                "kind": "BinaryExpr",
                "op": "and",
                "left": lit(True, "bool"),
                "right": lit(False, "bool"),
            }
        )
    )
    assert "or" in tr.translate_expression(
        ASTNode(
            {
                "kind": "BinaryExpr",
                "op": "or",
                "left": lit(True, "bool"),
                "right": lit(False, "bool"),
            }
        )
    )
    assert tr.translate_expression(
        ASTNode(
            {
                "kind": "BinaryExpr",
                "op": "==",
                "left": lit("a", "string"),
                "right": lit("b", "string"),
            }
        )
    ).startswith("(")
    with pytest.raises(UnsupportedNodeError):
        tr.translate_expression(
            ASTNode({"kind": "BinaryExpr", "op": "?", "left": lit(1), "right": lit(2)})
        )
    with pytest.raises(UnsupportedNodeError):
        tr.translate_expression(ASTNode({"kind": "BinaryExpr", "op": "+", "left": lit(1)}))
    with pytest.raises(UnsupportedNodeError):
        tr.translate_expression(ASTNode({"kind": "UnaryExpr", "op": "not"}))
    assert tr.translate_expression(
        ASTNode({"kind": "UnaryExpr", "op": "not", "operand": lit(True, "bool")})
    ).startswith("(not")
    assert tr.translate_expression(
        ASTNode({"kind": "UnaryExpr", "op": "-", "operand": lit(1)})
    ).startswith("pine_mul")
    assert (
        tr.translate_expression(ASTNode({"kind": "UnaryExpr", "op": "+", "operand": lit(1)})) == "1"
    )
    with pytest.raises(UnsupportedNodeError):
        tr.translate_expression(ASTNode({"kind": "UnaryExpr", "op": "~", "operand": lit(1)}))
    with pytest.raises(UnsupportedNodeError):
        tr.translate_expression(
            ASTNode({"kind": "ConditionalExpr", "condition": lit(True, "bool"), "then": lit(1)})
        )

    switch_subject = {
        "kind": "SwitchStructure",
        "expression": ident("local"),
        "cases": [
            {"kind": "SwitchCase", "value": lit(1), "expression": lit("one", "string")},
            {"kind": "SwitchCase", "default": True, "expression": lit("other", "string")},
        ],
    }
    assert "if" in tr.translate_expression(ASTNode(switch_subject))
    switch_conditions = {
        "kind": "SwitchExpression",
        "cases": [
            {"kind": "SwitchCase", "condition": lit(True, "bool"), "expression": lit(1)},
            {"kind": "SwitchCase", "default": True, "expression": lit(2)},
        ],
    }
    assert "pine_bool" in tr.translate_expression(ASTNode(switch_conditions))
    assert tr.translate_expression(ASTNode({"kind": "TupleExpr", "values": [lit(1)]})) == "(1,)"
    assert "PineArray" in tr.translate_expression(
        ASTNode({"kind": "ArrayLiteral", "items": [lit(1), lit(2)]})
    )
    assert "PineMap" in tr.translate_expression(
        ASTNode(
            {
                "kind": "MapLiteral",
                "entries": [{"kind": "MapEntry", "key": lit("a", "string"), "value": lit(1)}],
            }
        )
    )
    with pytest.raises(UnsupportedNodeError):
        tr.translate_expression(
            ASTNode(
                {"kind": "MapLiteral", "entries": [{"kind": "MapEntry", "key": lit("a", "string")}]}
            )
        )
    with pytest.raises(UnsupportedNodeError):
        tr.translate_expression(ASTNode({"kind": "MatrixLiteral"}))
    with pytest.raises(UnsupportedNodeError):
        tr.translate_expression(ASTNode({"kind": "UnknownExpr"}))

    for name in [
        "bar_index",
        "na",
        "group",
        "hl2",
        "hlc3",
        "ohlc4",
        "hlcc4",
        "year",
        "strategy",
        "local",
    ]:
        assert tr.translate_expression(ASTNode(ident(name)))
    for raw in [
        member("syminfo", "tickerid"),
        member("timeframe", "period"),
        member("timeframe", "isseconds"),
        member("barstate", "isfirst"),
        member("strategy", "long"),
        member("strategy", "short"),
        member("strategy", "equity"),
        member("strategy", "cash"),
        member("strategy", "percent_of_equity"),
        member("strategy", "fixed"),
        member("strategy.commission", "percent"),
        member("strategy.oca", "cancel"),
        member("barmerge", "lookahead_on"),
        member("display", "all"),
        member("extend", "right"),
        member("color", "green"),
        member("array", "new"),
        member("map", "new"),
        member("matrix", "new"),
        member("request", "security"),
        member("ta", "hl2"),
        member("ta", "atr20"),
        member("ta", "ema"),
        member("math", "sqrt"),
        member("str", "tostring"),
        member("line", "set_x1"),
    ]:
        assert tr.translate_expression(ASTNode(raw))
    with pytest.raises(UnsupportedNodeError):
        tr.translate_expression(
            ASTNode({"kind": "MemberAccessExpr", "object": {"kind": "Unknown"}, "member": "x"})
        )
    with pytest.raises(UnsupportedNodeError):
        tr.translate_expression(ASTNode({"kind": "MemberAccessExpr", "member": "x"}))

    assert (
        tr.translate_expression(
            ASTNode({"kind": "HistoryRefExpr", "base": ident("close"), "offset": lit(1)})
        )
        == "self.rt.close[1]"
    )
    assert "timefunc.year" in tr.translate_expression(
        ASTNode({"kind": "HistoryRefExpr", "base": ident("year"), "offset": lit(1)})
    )
    assert "pine_div" in tr.translate_expression(
        ASTNode({"kind": "HistoryRefExpr", "base": ident("hl2"), "offset": lit(1)})
    )
    assert "pine_div" in tr.translate_expression(
        ASTNode({"kind": "HistoryRefExpr", "base": ident("hlc3"), "offset": lit(1)})
    )
    assert "pine_div" in tr.translate_expression(
        ASTNode({"kind": "HistoryRefExpr", "base": ident("ohlc4"), "offset": lit(1)})
    )
    assert "pine_div" in tr.translate_expression(
        ASTNode({"kind": "HistoryRefExpr", "base": ident("hlcc4"), "offset": lit(1)})
    )
    with pytest.raises(TypeResolutionError):
        tr.translate_expression(
            ASTNode({"kind": "HistoryRefExpr", "base": ident("arr"), "offset": lit(1)})
        )
    with pytest.raises(TypeResolutionError):
        tr.translate_expression(
            ASTNode({"kind": "HistoryRefExpr", "base": lit(1), "offset": lit(1)})
        )
    with pytest.raises(UnsupportedNodeError):
        tr.translate_expression(ASTNode({"kind": "HistoryRefExpr", "base": ident("close")}))

    if_expr = {
        "kind": "IfStructure",
        "condition": lit(True, "bool"),
        "then_block": {
            "kind": "Block",
            "statements": [{"kind": "ExpressionStatement", "expression": lit(1)}],
        },
        "else_block": {
            "kind": "Block",
            "statements": [{"kind": "ExpressionStatement", "expression": lit(2)}],
        },
    }
    assert "if pine_bool" in tr.translate_expression(ASTNode(if_expr))
    with pytest.raises(UnsupportedNodeError):
        tr.translate_expression(ASTNode({"kind": "IfStructure", "condition": lit(True, "bool")}))


def test_call_low_level_branch_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    tr = Translator(
        compile_profile="diagnostic",
        visual_policy="record",
        allow_external_library_stubs=True,
        allow_unsupported_request_stubs=True,
        allow_invalid_ast=True,
    )
    monkeypatch.setattr(tr, "_bind_or_raise", lambda name, node: None)
    with pytest.raises(UnsupportedNodeError):
        tr._translate_call(ASTNode({"kind": "CallExpr"}), runtime_expr="self.rt")
    with pytest.raises(UnsupportedBuiltinError):
        tr._translate_call(
            ASTNode({"kind": "CallExpr", "callee": {"kind": "Unknown"}}), runtime_expr="self.rt"
        )
    with pytest.raises(UnsupportedBuiltinError):
        tr._translate_na_helper_call("na", ASTNode(call("na", [])), runtime_expr="self.rt")
    with pytest.raises(TypeResolutionError):
        tr._translate_na_helper_call(
            "na", ASTNode(call("na", [arg(lit(True, "bool"))])), runtime_expr="self.rt"
        )

    short_security = ASTNode(call(member("request", "security"), []))
    with pytest.raises(UnsupportedBuiltinError):
        tr._translate_request_security(short_security, runtime_expr="self.rt")
    security = ASTNode(
        call(
            member("request", "security"),
            [
                arg(lit("A", "string")),
                arg(lit("D", "string")),
                arg(ident("close")),
                arg(lit("off", "string"), "lookahead"),
            ],
        )
    )
    assert "request_security" in tr._translate_request_security(security, runtime_expr="self.rt")
    nested = ASTNode(
        call(
            member("request", "security"),
            [
                arg(lit("A", "string")),
                arg(lit("D", "string")),
                arg(call(member("request", "financial"), [])),
            ],
        )
    )
    assert "request_security" in tr._translate_request_security(nested, runtime_expr="self.rt")
    strict = Translator(compile_profile="diagnostic", strict=True)
    monkeypatch.setattr(strict, "_bind_or_raise", lambda name, node: None)
    with pytest.raises(UnsupportedBuiltinError):
        strict._translate_request_security(nested, runtime_expr="self.rt")

    with pytest.raises(UnsupportedBuiltinError):
        tr._translate_request_security_lower_tf(
            ASTNode(call(member("request", "security_lower_tf"), [])), runtime_expr="self.rt"
        )
    lower_tf = ASTNode(
        call(
            member("request", "security_lower_tf"),
            [
                arg(lit("A", "string")),
                arg(lit("1", "string")),
                arg(ident("close")),
                arg(lit(False, "bool"), "ignore_invalid_symbol"),
            ],
        )
    )
    assert "expression_hint" in tr._translate_request_security_lower_tf(
        lower_tf, runtime_expr="self.rt"
    )
    assert "request_footprint" in tr._translate_request_footprint(
        ASTNode(call(member("request", "footprint"), [arg(lit("A", "string"))])),
        runtime_expr="self.rt",
    )
    no_stub = Translator(compile_profile="diagnostic")
    with pytest.raises(UnsupportedBuiltinError):
        no_stub._translate_unsupported_request_call(
            "request.earnings", ASTNode(call(member("request", "earnings"))), runtime_expr="self.rt"
        )
    assert (
        tr._translate_unsupported_request_call(
            "request.earnings", ASTNode(call(member("request", "earnings"))), runtime_expr="self.rt"
        )
        == "na"
    )

    for var_name, type_ref in [("a", "array"), ("m", "matrix")]:
        info = tr.ctx.declare_var(
            var_name,
            type_ref=type_ref,
            qualifier="series",
            declaration_kind="normal",
            is_series=True,
            is_mutable=True,
            loc=None,
            prefer_py_name=var_name,
        )
        info.type_info = make_type_info(type_ref, "series")

    tr.ctx.import_aliases["lib"] = {"library": "lib"}
    assert "_external_library_call" in tr._translate_external_library_call(
        "lib.foo",
        ASTNode(call(member("lib", "foo"), [arg(lit(1)), arg(lit(2), "x")])),
        runtime_expr="self.rt",
    )
    assert "pine_color.new" in tr._translate_color_new(
        "color.new",
        ASTNode(call(member("color", "new"), [arg(member("color", "red")), arg(lit(10))])),
        runtime_expr="self.rt",
    )

    for name, raw in [
        ("array.new", call(member("array", "new"), [arg(lit(2))])),
        ("array.new", call(member("array", "new"), [])),
        ("array.from", call(member("array", "from"), [arg(lit(1)), arg(lit(2))])),
        (
            "array.new_float",
            call(member("array", "new_float"), [arg(lit(2)), arg(lit(0.0, "float"))]),
        ),
        ("map.new", call(member("map", "new"), [])),
        (
            "matrix.new",
            call(member("matrix", "new"), [arg(lit(2)), arg(lit(2)), arg(lit(0.0, "float"))]),
        ),
        ("matrix.rows", call(member("matrix", "rows"), [arg(ident("m"))])),
        ("array.push", call(member("array", "push"), [arg(ident("a")), arg(lit(1))])),
        ("array.size", call(member("array", "size"), [arg(ident("a"))])),
        ("array.copy", call(member("array", "copy"), [arg(ident("a"))])),
    ]:
        assert tr._translate_reference_call(name, ASTNode(raw), runtime_expr="self.rt")
    with pytest.raises(KeyError):
        tr._translate_reference_call(
            "array.join",
            ASTNode(call(member("array", "join"), [arg(ident("a"))])),
            runtime_expr="self.rt",
        )

    for name in [
        "strategy.closedtrades.entry_price",
        "strategy.risk.allow_entry_in",
        "strategy.entry",
    ]:
        assert tr._translate_strategy_call(
            name,
            ASTNode(call(member("strategy", name.split(".")[-1]), [arg(lit("L", "string"))])),
            runtime_expr="self.rt",
        )
    with pytest.raises(KeyError):
        tr._translate_strategy_call(
            "strategy.unknown",
            ASTNode(call(member("strategy", "unknown"), [arg(lit("L", "string"))])),
            runtime_expr="self.rt",
        )
    strict_strategy = Translator(compile_profile="diagnostic", strict=True)
    monkeypatch.setattr(strict_strategy, "_bind_or_raise", lambda name, node: None)
    with pytest.raises(UnsupportedBuiltinError):
        strict_strategy._translate_strategy_call(
            "strategy.unknown", ASTNode(call(member("strategy", "unknown"))), runtime_expr="self.rt"
        )

    assert tr._translate_visual_call(
        "plot",
        ASTNode(
            call(
                "plot",
                [
                    arg(ident("close")),
                    arg(lit("C", "string"), "title"),
                    arg(lit("all", "string"), "display"),
                ],
            )
        ),
        runtime_expr="self.rt",
    ).startswith("self._visual_call")
    assert tr._translate_visual_call(
        "hline", ASTNode(call("hline", [arg(lit(1))])), runtime_expr="self.rt"
    ).startswith("self._visual_call")
    assert tr._translate_input_runtime_lookup(ASTNode(call(member("input", "int"), [arg(lit(1))])))

    assert tr._translate_series_source_argument(
        ASTNode(
            {
                "kind": "Call",
                "callee": {"kind": "MemberAccess", "object": ident("ta"), "member": "hl2"},
                "arguments": [],
            }
        ),
        runtime_expr="self.rt",
    )
    original_translate_expression = tr.translate_expression
    tr.translate_expression = lambda node, runtime_expr="self.rt": "42"  # type: ignore[method-assign]
    assert "__tmp" in tr._translate_series_source_argument(
        ASTNode({"kind": "Call", "callee": ident("foo"), "arguments": []}), runtime_expr="self.rt"
    )
    assert "__tmp" in tr._translate_series_source_argument(
        ASTNode({"kind": "BinaryExpr", "op": "+", "left": ident("close"), "right": lit(1)}),
        runtime_expr="self.rt",
    )
    tr.translate_expression = original_translate_expression  # type: ignore[method-assign]
    assert (
        tr._translate_series_source_argument(ASTNode(ident("close")), runtime_expr="self.rt")
        == "self.rt.close"
    )
    assert "hlc3_series" in tr._translate_series_source_argument(
        ASTNode(ident("hlc3")), runtime_expr="self.rt"
    )
    tr.ctx.declare_var(
        "s",
        type_ref="float",
        qualifier="series",
        declaration_kind="normal",
        is_series=True,
        is_mutable=True,
        loc=None,
        prefer_py_name="s",
    )
    assert (
        tr._translate_series_source_argument(ASTNode(ident("s")), runtime_expr="self.rt")
        == "self.s"
    )
    assert "pine_add" in tr._translate_series_source_argument(
        ASTNode({"kind": "BinaryExpr", "op": "+", "left": ident("close"), "right": ident("open")}),
        runtime_expr="request_rt",
    )
    assert "__tmp" in tr._translate_series_source_argument(
        ASTNode({"kind": "BinaryExpr", "op": "+", "left": ident("close"), "right": ident("open")}),
        runtime_expr="self.rt",
    )

    for name, raw in [
        ("ta.dmi", call(member("ta", "dmi"), [arg(lit(14)), arg(lit(14))])),
        (
            "ta.sar",
            call(
                member("ta", "sar"),
                [arg(lit(0.02, "float")), arg(lit(0.02, "float")), arg(lit(0.2, "float"))],
            ),
        ),
        ("ta.tr", call(member("ta", "tr"), [])),
        ("ta.ema", call(member("ta", "ema"), [arg(ident("hlc3")), arg(lit(9))])),
        (
            "ta.valuewhen",
            call(
                member("ta", "valuewhen"),
                [
                    arg(ident("close"), "condition"),
                    arg(ident("open"), "source"),
                    arg(lit(0), "occurrence"),
                ],
            ),
        ),
    ]:
        assert tr._translate_ta_call(name, ASTNode(raw), runtime_expr="self.rt")
    assert tr._translate_math_call(
        "math.sqrt",
        ASTNode(call(member("math", "sqrt"), [arg(lit(4)), arg(lit(5), "unexpected")])),
        runtime_expr="self.rt",
    )
    assert tr._translate_str_call(
        "str.tostring",
        ASTNode(
            call(member("str", "tostring"), [arg(lit(4)), arg(lit("x", "string"), "unexpected")])
        ),
        runtime_expr="self.rt",
    )


def test_release_polish_time_emitter_edge_matrix() -> None:
    tr = Translator(compile_profile="diagnostic")
    emitter = PineTimeEmitter(tr)
    date = ASTNode(call("year", [arg(lit(123)), arg(lit("UTC", "string"), "timezone")]))
    assert emitter.translate_date_helper_call("year", date, runtime_expr="self.rt").endswith(
        "timezone='UTC', runtime=self.rt)"
    )

    assert emitter.translate_timestamp_call(
        ASTNode(call("timestamp", [arg(lit("2024-01-02 03:04:05 +0000", "string"))]))
    ).isdigit()
    assert emitter.translate_timestamp_call(
        ASTNode(call("timestamp", [arg(lit("2024-01-02T03:04:05+0000", "string"))]))
    ).isdigit()
    assert emitter.translate_timestamp_call(
        ASTNode(call("timestamp", [arg(lit("2024-01-02 03:04 +0000", "string"))]))
    ).isdigit()
    assert emitter.translate_timestamp_call(
        ASTNode(
            call(
                "timestamp",
                [
                    arg(lit("UTC", "string")),
                    arg(lit(2024)),
                    arg(lit(1)),
                    arg(lit(2)),
                    arg(lit(3)),
                    arg(lit(4)),
                    arg(lit(5)),
                ],
            )
        )
    ).isdigit()
    assert "timestamp_components" in emitter.translate_timestamp_call(
        ASTNode(
            call(
                "timestamp",
                [
                    arg(lit("UTC", "string")),
                    arg(ident("year")),
                    arg(lit(1)),
                    arg(lit(2)),
                    arg(lit(3)),
                    arg(lit(4)),
                ],
            )
        )
    )
    assert "timefunc.time(" in emitter.translate_time_call(
        "time", ASTNode(call("time", [arg(lit("D", "string"))])), runtime_expr="self.rt"
    )
    assert "timefunc.time_close(" in emitter.translate_time_call(
        "time_close",
        ASTNode(call("time_close", [arg(lit("D", "string"), "timeframe")])),
        runtime_expr="self.rt",
    )

    with pytest.raises(UnsupportedBuiltinError):
        emitter.translate_timestamp_call(ASTNode(call("timestamp", [])))
    with pytest.raises(UnsupportedBuiltinError):
        emitter.translate_timestamp_call(
            ASTNode(call("timestamp", [arg(lit("UTC", "string"), "tz")]))
        )
    with pytest.raises(UnsupportedBuiltinError):
        emitter.translate_timestamp_call(ASTNode(call("timestamp", [arg(lit(1))])))
    with pytest.raises(UnsupportedBuiltinError):
        emitter.translate_timestamp_call(
            ASTNode(call("timestamp", [arg(lit("UTC", "string")), arg(lit(2024))]))
        )
    with pytest.raises(UnsupportedBuiltinError):
        emitter.translate_timestamp_call(
            ASTNode(
                call(
                    "timestamp",
                    [
                        arg(lit("UTC", "string")),
                        arg(lit(2024), "year"),
                        arg(lit(1)),
                        arg(lit(2)),
                        arg(lit(3)),
                        arg(lit(4)),
                    ],
                )
            )
        )
    with pytest.raises(UnsupportedBuiltinError):
        emitter.translate_timestamp_call(
            ASTNode(
                call(
                    "timestamp",
                    [
                        arg(lit("UTC", "string")),
                        arg(lit(2024)),
                        arg(lit(13)),
                        arg(lit(2)),
                        arg(lit(3)),
                        arg(lit(4)),
                    ],
                )
            )
        )
    with pytest.raises(UnsupportedBuiltinError):
        emitter.translate_timestamp_call(
            ASTNode(call("timestamp", [arg(lit("bad format", "string"))]))
        )
    assert _timezone_for_name("UTC").utcoffset(None).total_seconds() == 0
    with pytest.raises(UnsupportedBuiltinError):
        _timezone_for_name("Mars/Olympus")


def test_release_polish_declaration_metadata_edges() -> None:
    tr = Translator(compile_profile="diagnostic")
    non_call = ASTNode(ident("x"))
    assert declaration_call_arguments(non_call) == []
    legacy_arg = ASTNode(
        {
            "kind": "CallExpr",
            "arguments": [
                {"kind": "Identifier", "name": "overlay"},
                {"kind": "Argument", "name": "title", "expression": lit("T", "string")},
            ],
        }
    )
    pairs = declaration_call_arguments(legacy_arg)
    assert len(pairs) == 2
    assert extract_declaration_title(tr, ASTNode({"kind": "IndicatorDeclaration"})) == "Generated"
    assert (
        extract_declaration_title(
            tr,
            ASTNode(
                {
                    "kind": "IndicatorDeclaration",
                    "call": call("indicator", [arg(lit("Title", "string"))]),
                }
            ),
        )
        == "Title"
    )
    assert literal_or_rendered(ASTNode(lit(1)), "ignored") == 1
    assert literal_or_rendered(ASTNode(member("color", "red")), "'red'") == "red"
    assert (
        literal_or_rendered(ASTNode(member("color", "red")), "pine_color.red") == "pine_color.red"
    )

    declaration = ASTNode(
        {
            "kind": "StrategyDeclaration",
            "call": call(
                "strategy",
                [
                    arg(lit("S", "string")),
                    arg(lit(True, "bool"), "overlay"),
                    arg(lit(1), "unknown_arg"),
                ],
            ),
        }
    )
    collect_declaration_metadata(tr, declaration, {"indicator": {"title"}, "diagnostic": {"title"}})
    assert "unknown_arg" in tr.ctx.unsupported_declaration_args
    strict = Translator(compile_profile="diagnostic", strict=True)
    with pytest.raises(UnsupportedBuiltinError):
        collect_declaration_metadata(strict, declaration, {"diagnostic": {"title"}})

    strategy = Translator(compile_profile="diagnostic", strict=False)
    strategy.ctx.mode = "strategy"
    kwargs = strategy_context_kwargs(
        strategy,
        declaration,
        {"overlay"},
        {"strategy": {"title", "overlay"}},
    )
    assert kwargs == [("overlay", "True")]
    assert strategy.ctx.strategy_metadata["unknown_arg"] == 1
    strict_strategy = Translator(compile_profile="diagnostic", strict=True)
    strict_strategy.ctx.mode = "strategy"
    with pytest.raises(UnsupportedBuiltinError):
        strategy_context_kwargs(strict_strategy, declaration, {"overlay"}, {"strategy": {"title"}})


def test_release_polish_statement_emission_edge_matrix() -> None:
    tr = Translator(compile_profile="diagnostic", allow_external_library_stubs=True)
    for node in [
        ASTNode({"kind": "ImportDeclaration", "alias": "lib", "path": "u/lib", "library": "lib"}),
        ASTNode(
            {
                "kind": "Block",
                "statements": [{"kind": "BreakStatement"}, {"kind": "ContinueStatement"}],
            }
        ),
        ASTNode(
            {"kind": "AlertCondition", "condition": lit(True, "bool"), "title": lit("T", "string")}
        ),
    ]:
        tr._emit_statement(node)
    with pytest.raises(UnsupportedNodeError):
        tr._emit_statement(ASTNode({"kind": "ExpressionStatement"}))
    with pytest.raises(UnsupportedNodeError):
        tr._emit_statement(ASTNode({"kind": "NoSuchStatement"}))
    with pytest.raises(UnsupportedNodeError):
        tr._emit_var_declaration(ASTNode({"kind": "VarDeclaration", "name": "missing"}))

    for name, mode in [("normal_v", "normal"), ("var_v", "var"), ("varip_v", "varip")]:
        tr._emit_var_declaration(
            ASTNode({"kind": "VarDeclaration", "name": name, "mode": mode, "initializer": lit(1)})
        )
    object_info = tr._resolve_or_declare_var(
        ASTNode({"kind": "VarDeclaration", "name": "obj", "type": "line"}), "obj"
    )
    assert object_info.type_info is not None

    tr.ctx.enter_scope("block")
    tr._emit_var_declaration(
        ASTNode({"kind": "VarDeclaration", "name": "local_v", "initializer": lit(2)})
    )
    tr._emit_var_declaration(
        ASTNode(
            {
                "kind": "VarDeclaration",
                "name": "local_varip",
                "mode": "varip",
                "initializer": lit(3),
            }
        )
    )
    tr.ctx.exit_scope()

    assert tr._tuple_targets(ASTNode({"kind": "TupleDeclaration", "targets": ["a", "_"]})) == [
        "a",
        "_",
    ]
    assert tr._tuple_targets(
        ASTNode(
            {
                "kind": "TupleDeclaration",
                "targets": [
                    ident("b"),
                    {"kind": "TupleDiscard"},
                    {"kind": "TupleTarget", "name": "c"},
                ],
            }
        )
    ) == ["b", "_", "c"]
    with pytest.raises(UnsupportedNodeError):
        tr._tuple_targets(ASTNode({"kind": "TupleDeclaration", "targets": "bad"}))
    with pytest.raises(UnsupportedNodeError):
        tr._tuple_targets(ASTNode({"kind": "TupleDeclaration", "targets": [{"kind": "Bad"}]}))
    with pytest.raises(UnsupportedNodeError):
        tr._emit_tuple_declaration(ASTNode({"kind": "TupleDeclaration", "targets": ["x"]}))
    with pytest.raises(UnsupportedNodeError):
        tr._emit_tuple_declaration(
            ASTNode({"kind": "TupleDeclaration", "targets": [], "initializer": lit(1)})
        )

    tr._emit_tuple_declaration(
        ASTNode(
            {
                "kind": "TupleDeclaration",
                "targets": ["macd", "signal", "hist"],
                "initializer": call(
                    member("ta", "macd"),
                    [arg(ident("close")), arg(lit(12)), arg(lit(26)), arg(lit(9))],
                ),
            }
        )
    )
    tr._emit_tuple_declaration(
        ASTNode(
            {
                "kind": "TupleDeclaration",
                "targets": ["ro", "rh", "rl", "rc"],
                "initializer": call(
                    member("request", "security"),
                    [
                        arg(lit("A", "string")),
                        arg(lit("D", "string")),
                        arg(
                            {
                                "kind": "TupleExpr",
                                "elements": [
                                    ident("open"),
                                    ident("high"),
                                    ident("low"),
                                    ident("close"),
                                ],
                            }
                        ),
                    ],
                ),
            }
        )
    )

    with pytest.raises(UnsupportedNodeError):
        tr._emit_reassignment(ASTNode({"kind": "Reassignment", "target": ident("x")}))
    with pytest.raises(UnsupportedNodeError):
        tr._emit_reassignment(
            ASTNode({"kind": "Reassignment", "target": member("x", "y"), "value": lit(1)})
        )
    tr._emit_reassignment(
        ASTNode({"kind": "Reassignment", "target": ident("normal_v"), "op": "+=", "value": lit(2)})
    )
    tr._emit_reassignment(
        ASTNode({"kind": "Reassignment", "target": ident("varip_v"), "op": ":=", "value": lit(4)})
    )

    with pytest.raises(UnsupportedNodeError):
        tr._emit_if(ASTNode({"kind": "IfStructure", "condition": lit(True, "bool")}))
    tr._emit_if(
        ASTNode(
            {
                "kind": "IfStructure",
                "condition": lit(True, "bool"),
                "then_block": {"kind": "Block", "statements": []},
                "else_if_branches": [
                    {
                        "kind": "ElseIfBranch",
                        "condition": lit(False, "bool"),
                        "block": {"kind": "Block", "statements": []},
                    }
                ],
                "else_block": {"kind": "Block", "statements": []},
            }
        )
    )
    with pytest.raises(UnsupportedNodeError):
        tr._emit_if(
            ASTNode(
                {
                    "kind": "IfStructure",
                    "condition": lit(True, "bool"),
                    "then_block": {"kind": "Block", "statements": []},
                    "else_if_branches": [{"kind": "ElseIfBranch", "condition": lit(True, "bool")}],
                }
            )
        )

    with pytest.raises(UnsupportedNodeError):
        tr._emit_for_range(ASTNode({"kind": "ForRangeStructure", "variable": "i"}))
    tr._emit_for_range(
        ASTNode(
            {
                "kind": "ForRangeStructure",
                "variable": "i",
                "start": lit(1),
                "end": lit(3),
                "step": lit(1),
            }
        )
    )
    tr._emit_for_range(
        ASTNode(
            {
                "kind": "ForRangeStructure",
                "variable": "j",
                "start": lit(1),
                "end": lit(3),
                "body": {"kind": "Block", "statements": []},
            }
        )
    )
    with pytest.raises(UnsupportedNodeError):
        tr._for_in_target_names(ASTNode({"kind": "ForInStructure"}))
    arr_info = tr.ctx.declare_var(
        "arr",
        type_ref="array",
        qualifier="series",
        declaration_kind="normal",
        is_series=True,
        is_mutable=True,
        loc=None,
        prefer_py_name="arr",
    )
    arr_info.type_info = make_type_info("array", "series")
    tr._emit_for_in(
        ASTNode(
            {
                "kind": "ForInStructure",
                "target": ident("item"),
                "iterable": ident("arr"),
                "body": {"kind": "Block", "statements": []},
            }
        )
    )
    tr._emit_for_in(
        ASTNode(
            {
                "kind": "ForInStructure",
                "names": ["k", "v"],
                "iterable": ident("arr"),
                "body": {"kind": "Block", "statements": [{"kind": "ContinueStatement"}]},
            }
        )
    )
    with pytest.raises(UnsupportedNodeError):
        tr._emit_for_in(ASTNode({"kind": "ForInStructure", "target": ident("x")}))

    with pytest.raises(UnsupportedNodeError):
        tr._emit_while(ASTNode({"kind": "WhileStructure"}))
    tr._emit_while(
        ASTNode(
            {
                "kind": "WhileStructure",
                "condition": lit(True, "bool"),
                "body": {"kind": "Block", "statements": []},
            }
        )
    )
    tr._emit_switch(ASTNode({"kind": "SwitchStructure"}))
    tr._emit_switch(
        ASTNode(
            {
                "kind": "SwitchStructure",
                "expression": ident("normal_v"),
                "cases": [
                    {"kind": "SwitchCase", "value": lit(1), "expression": lit("one", "string")},
                    {
                        "kind": "SwitchCase",
                        "default": True,
                        "body": {"kind": "Block", "statements": [{"kind": "BreakStatement"}]},
                    },
                ],
            }
        )
    )
    tr._record_import_alias(ASTNode({"kind": "ImportDeclaration"}))
    rejecting = Translator(compile_profile="diagnostic")
    with pytest.raises(UnsupportedBuiltinError):
        rejecting._record_import_alias(ASTNode({"kind": "ImportDeclaration", "alias": "nope"}))


def test_release_polish_small_helper_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(UnsupportedNodeError):
        call_arguments(ASTNode(call("x", [{"kind": "Argument", "name": None}])))
    assert (
        ordered_call_arguments(
            "math.sqrt",
            ASTNode(call(member("math", "sqrt"), [arg(lit(1), "number"), arg(lit(2))])),
        )[-1][0]
        is None
    )
    assert type_matches("object", frozenset({"object"}))
    assert type_matches("line", frozenset({"PineObjectId"}))
    assert type_matches("PineArray", frozenset({"array"}))
    assert (
        bind_builtin_call(
            "ta.ema",
            [
                ("source", TypeInfo("object", "simple", origin="untyped_param")),
                ("length", TypeInfo("object", "simple", origin="untyped_param")),
            ],
        )
        == []
    )
    assert bind_builtin_call(
        "ta.ema", [("source", TypeInfo("float", "series")), (None, TypeInfo("int", "simple"))]
    )
    assert bind_builtin_call("does.not.exist", [])

    tr = Translator(compile_profile="diagnostic", allow_external_library_stubs=True)
    for var_name in ("foot", "obj"):
        tr.ctx.declare_var(
            var_name,
            type_ref="object",
            qualifier="series",
            declaration_kind="normal",
            is_series=True,
            is_mutable=True,
            loc=None,
            prefer_py_name=var_name,
        )
    tr.ctx.import_aliases["lib"] = {}
    assert dispatch_fallback_call(
        tr,
        "lib.foo",
        ASTNode(call(member("lib", "foo"))),
        ASTNode(member("lib", "foo")),
        runtime_expr="self.rt",
    )
    assert dispatch_fallback_call(
        tr,
        "foot.buy_volume",
        ASTNode(call(member("foot", "buy_volume"), [arg(lit(1))])),
        ASTNode(member("foot", "buy_volume")),
        runtime_expr="self.rt",
    )
    tr.methods.add("m")
    assert "self.m" in dispatch_fallback_call(
        tr,
        "obj.m",
        ASTNode(call(member("obj", "m"), [arg(lit(1))])),
        ASTNode(member("obj", "m")),
        runtime_expr="self.rt",
    )
    tr.functions.add("foo")
    assert "self.foo" in dispatch_fallback_call(
        tr,
        "foo",
        ASTNode(call("foo", [arg(lit(1))])),
        ASTNode(ident("foo")),
        runtime_expr="self.rt",
    )
    tr.methods.add("bar")
    assert "self.bar" in dispatch_fallback_call(
        tr,
        "bar",
        ASTNode(call("bar", [arg(lit(1))])),
        ASTNode(ident("bar")),
        runtime_expr="self.rt",
    )
    assert "MyType" in dispatch_fallback_call(
        tr,
        "MyType",
        ASTNode(call("MyType", [arg(lit(1), "x")])),
        ASTNode(ident("MyType")),
        runtime_expr="self.rt",
    )
    assert "pine_int" in dispatch_fallback_call(
        tr,
        "int",
        ASTNode(call("int", [arg(lit(1.2, "float"))])),
        ASTNode(ident("int")),
        runtime_expr="self.rt",
    )
    with pytest.raises(UnsupportedBuiltinError):
        dispatch_fallback_call(
            tr,
            "unknown",
            ASTNode(call("unknown")),
            ASTNode(ident("unknown")),
            runtime_expr="self.rt",
        )
    assert (
        dispatch_call(
            tr,
            "exact",
            ASTNode(call("exact")),
            ASTNode(ident("exact")),
            runtime_expr="self.rt",
            exact_handlers={"exact": lambda _tr, _node, runtime_expr: f"exact:{runtime_expr}"},
            prefix_handlers=[],
        )
        == "exact:self.rt"
    )
    assert dispatch_call(
        tr,
        "pre.foo",
        ASTNode(call(member("pre", "foo"))),
        ASTNode(member("pre", "foo")),
        runtime_expr="self.rt",
        exact_handlers={},
        prefix_handlers=[
            ("pre.", lambda _tr, name, _node, runtime_expr: f"prefix:{name}:{runtime_expr}")
        ],
    ).startswith("prefix:pre.foo")

    # Common/strategy/time handler adapters are intentionally thin; execute all of them.
    monkeypatch.setattr(tr, "_translate_input_runtime_lookup", lambda node: "input")
    monkeypatch.setattr(
        tr, "_translate_na_helper_call", lambda name, node, runtime_expr: f"{name}:{runtime_expr}"
    )
    monkeypatch.setattr(
        tr, "_translate_alert_call", lambda name, node, runtime_expr: f"{name}:{runtime_expr}"
    )
    monkeypatch.setattr(
        tr, "_translate_color_new", lambda name, node, runtime_expr: f"{name}:{runtime_expr}"
    )
    assert input_runtime(tr, ASTNode(call("input.int")), "rt") == "input"
    assert na(tr, ASTNode(call("na", [arg(lit(1))])), "rt") == "na:rt"
    assert nz(tr, ASTNode(call("nz", [arg(lit(1))])), "rt") == "nz:rt"
    assert fixnan(tr, ASTNode(call("fixnan", [arg(lit(1))])), "rt") == "fixnan:rt"
    assert alert(tr, ASTNode(call("alert", [arg(lit("x", "string"))])), "rt") == "alert:rt"
    assert alertcondition(tr, ASTNode(call("alertcondition")), "rt") == "alertcondition:rt"
    assert color_new(tr, ASTNode(call(member("color", "new"))), "rt") == "color.new:rt"
    monkeypatch.setattr(
        tr, "_translate_strategy_call", lambda name, node, runtime_expr: f"{name}:{runtime_expr}"
    )
    assert (
        builtin_strategy_prefix(
            tr, "strategy.entry", ASTNode(call(member("strategy", "entry"))), "rt"
        )
        == "strategy.entry:rt"
    )
    assert strategy_long(tr, ASTNode(call(member("strategy", "long"))), "rt") == "strategy.long:rt"
    assert (
        strategy_short(tr, ASTNode(call(member("strategy", "short"))), "rt") == "strategy.short:rt"
    )
    assert timestamp(
        tr, ASTNode(call("timestamp", [arg(lit("2024-01-01 00:00 +0000", "string"))])), "rt"
    ).isdigit()
    assert make_date_helper("month")(tr, ASTNode(call("month")), "rt").startswith(
        "rt.timefunc.month"
    )
    assert builtin_time_exact(tr, ASTNode(call("time")), "rt").startswith("rt.timefunc.time")
    assert builtin_time_close_exact(tr, ASTNode(call("time_close")), "rt").startswith(
        "rt.timefunc.time_close"
    )
    assert timeframe_change_exact(
        tr, ASTNode(call(member("timeframe", "change"), [arg(lit("D", "string"))])), "rt"
    ).startswith("rt.timefunc.change")

    manager = ImportManager()
    assert manager.require_import("json") == "json"
    assert manager.require_import("os", alias="pine_os") == "pine_os"
    assert "import os as pine_os" in manager.render()
    assert make_type_info("integer", None).base_type == "int"
    assert make_type_info("str", None).base_type == "string"
    assert make_type_info("array", None).is_reference_type
    assert (
        member_chain(ASTNode({"kind": "GenericInstantiationExpr", "base": member("array", "new")}))
        == "array.new"
    )
    assert (
        member_chain(
            ASTNode({"kind": "MemberAccessExpr", "object": {"kind": "Unknown"}, "member": "x"})
        )
        is None
    )
    assert visual_call_from_call_chain(None) is None
    assert frontend_diagnostic_visual_call({"code": "X", "details": {"callee": object()}}) is None


def test_release_polish_schema_validation_edges(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ensure_program_node([])  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ensure_program_node({"kind": "Script"})
    wrapped = ensure_program_node(
        {
            "ast": {"kind": "Program", "declaration": {"kind": "IndicatorDeclaration"}},
            "producer_metadata": {"producer": "pine2ast"},
        }
    )
    assert wrapped.raw["producer_metadata"]["producer"] == "pine2ast"
    result_wrapped = ensure_program_node(
        {
            "result": {
                "program": {"kind": "Program", "declaration": {"kind": "IndicatorDeclaration"}},
                "metadata": {"producer": "pine2ast"},
            }
        }
    )
    assert result_wrapped.raw["producer_metadata"]["producer"] == "pine2ast"
    node = ASTNode(
        {
            "kind": "Wrapper",
            "span": {"start": {"line": 1, "column": 2}, "end": {"line": 3, "column": 4}},
            "source": "x",
            "children": [{"kind": "Child"}],
            "body": {"statements": [{"kind": "Statement"}]},
            "value": [{"kind": "First"}],
        }
    )
    assert node.loc is not None and node.loc.line == 1
    assert node.source == "x"
    assert node.child("value").kind == "First"
    assert [child.kind for child in node.children("body", "children")] == ["Statement", "Child"]
    loc_node = ASTNode(
        {"kind": "Loc", "loc": {"line": 5, "column": 6, "end_line": 7, "end_col": 8}}
    )
    assert loc_node.loc is not None and loc_node.loc.end_line == 7
    path = tmp_path / "ast.json"
    path.write_text(
        json.dumps({"kind": "Program", "declaration": {"kind": "IndicatorDeclaration"}})
    )
    assert load_ast(path).kind == "Program"
    assert (
        normalized_program_dict(
            {"program": {"kind": "Program", "declaration": {"kind": "IndicatorDeclaration"}}}
        )["kind"]
        == "Program"
    )
    assert (
        "language must be"
        in validate_ast(ASTProgramProxy({"kind": "Program", "language": "python"}))[0]
    )


class ASTProgramProxy(ASTNode):
    @property
    def declaration(self) -> ASTNode | None:
        return self.child("declaration")


def test_release_polish_lowering_validation_negative_edges(tmp_path: Path) -> None:
    with pytest.raises(LoweringMatrixError):
        validate_lowering_matrix_payload(
            {"schema_version": "bad", "runtime_contract": "bad", "entries": []}
        )
    bad_entry = {
        "schema_version": "pine.ast2python.lowering_matrix.v1",
        "runtime_contract": "1.4",
        "entries": [
            {},
            {
                "ast_kind": "X",
                "priority": "bad",
                "runtime_contract": "bad",
                "status": "bad",
                "lowering": "bad",
                "tests": "bad",
                "diagnostics": "bad",
            },
            {
                "ast_kind": "X",
                "priority": "P0",
                "runtime_contract": "1.4",
                "status": "supported",
                "lowering": "supported",
                "tests": "covered",
                "diagnostics": [],
            },
        ],
    }
    with pytest.raises(LoweringMatrixError):
        validate_lowering_matrix_payload(bad_entry)
    with pytest.raises(LoweringMatrixError):
        validate_source_map_contract_payload(
            {
                "schema_version": "bad",
                "runtime_contract": "bad",
                "required_fields": "bad",
                "format": "bad",
            }
        )
    with pytest.raises(LoweringMatrixError):
        validate_source_map_contract_payload(
            {
                "schema_version": "pine.ast2python.source_map_contract.v1",
                "runtime_contract": "1.4",
                "required_fields": [],
                "format": "json-array",
            }
        )
    assert lowering_validate_main([]) == 0


def test_release_polish_cli_main_dispatch_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ast_path = tmp_path / "program.json"
    ast_path.write_text(json.dumps(with_valid_producer_metadata(program([]))))
    out_dir = tmp_path / "out"
    assert cli_main(["validate", str(ast_path)]) == 0
    assert cli_main(["translate", str(ast_path), "-o", str(out_dir), "--module-name", "m"]) == 0
    assert cli_main(["translate-many", str(ast_path), "-o", str(tmp_path / "many")]) == 0
    assert cli_main(["coverage", str(ast_path)]) == 0
    assert cli_main(["lowering-matrix", "validate"]) == 0
    assert cli_main(["source-map-contract", "validate"]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"kind": "Nope"}))
    assert cli_main(["validate", str(bad)]) == 1
    monkeypatch.setattr(sys, "argv", ["ast2python", "lowering-matrix", "validate"])


def test_release_polish_module_dynamic_imports_and_inputs() -> None:
    tr = Translator(compile_profile="diagnostic")
    rich_program = ensure_program_node(
        {
            "kind": "Program",
            "declaration": {"kind": "IndicatorDeclaration"},
            "items": [
                {"kind": "CallExpr", "callee": member("request", "footprint"), "arguments": []},
                {"kind": "ForInStructure", "target": ident("x"), "iterable": ident("xs")},
                {"kind": "TypeDeclaration", "name": "Point"},
                {"kind": "EnumDeclaration", "name": "Side"},
                {"kind": "MemberAccessExpr", "object": ident("color"), "member": "red"},
                {"kind": "MemberAccessExpr", "object": ident("ta"), "member": "hlc3"},
                ident("hlcc4"),
                {"kind": "CallExpr", "callee": ident("ta"), "arguments": []},
                {"kind": "CallExpr", "callee": member("ta", "ema"), "arguments": []},
                {"kind": "CallExpr", "callee": member("math", "sqrt"), "arguments": []},
                {"kind": "CallExpr", "callee": member("str", "tostring"), "arguments": []},
                {"kind": "CallExpr", "callee": member("array", "new"), "arguments": []},
            ],
        }
    )
    tr._declare_dynamic_imports(rich_program)
    imports_text = "\n".join(tr.ctx.imports.render())
    assert "request_footprint" in imports_text
    assert "pine_iter" in imports_text
    assert "dataclass" in imports_text and "Enum" in imports_text
    assert "pine_color" in imports_text
    assert "hlcc4_series" in imports_text

    input_tr = Translator(compile_profile="diagnostic")
    for idx, default in enumerate(
        [
            "pine_add(self.rt.open.current, pine_add(self.rt.high.current, pine_add(self.rt.low.current, self.rt.close.current)))",
            "pine_add(self.rt.high.current, pine_add(self.rt.low.current, self.rt.close.current))",
            "pine_add(self.rt.high.current, self.rt.low.current)",
            "pine_add(self.rt.high.current, self.rt.close.current)",
            "pine_add(self.rt.open.current, self.rt.close.current)",
            "self.rt.close.current",
            "self.rt.close",
        ]
    ):
        info = input_tr.ctx.declare_var(
            f"src{idx}",
            type_ref="source",
            qualifier="input",
            declaration_kind="input",
            is_series=True,
            is_mutable=False,
            loc=None,
            prefer_py_name=f"src{idx}",
        )
        input_tr.input_series.append(
            (info, "source", {"default_python": default, "public": {"type": "source"}})
        )
    scalar = input_tr.ctx.declare_var(
        "len_input",
        type_ref="int",
        qualifier="input",
        declaration_kind="input",
        is_series=True,
        is_mutable=False,
        loc=None,
        prefer_py_name="len_input",
    )
    input_tr.input_series.append(
        (
            scalar,
            "int",
            {"default_python": 14, "public": {"type": "int", "minval": 1, "maxval": 100}},
        )
    )
    input_tr._emit_init(ASTNode({"kind": "IndicatorDeclaration"}))
    rendered = input_tr.emitter.render()
    assert "ohlc4_series" in rendered
    assert "hlc3_series" in rendered
    assert "hl2_series" in rendered
    assert "hlcc4_series" in rendered
    assert "self.rt.close" in rendered
    assert "_input_value" in rendered

    lib_tr = Translator(compile_profile="diagnostic")
    lib_tr.ctx.mode = "library"
    lib_tr._emit_run()
    assert "results.append(None)" in lib_tr.emitter.render()
