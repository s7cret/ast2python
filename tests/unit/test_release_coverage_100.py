from __future__ import annotations

import builtins
import importlib.util
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import ast2python.binder_signatures as binder_signatures
import ast2python.cli.commands as cli_commands
import ast2python.cli.main as cli_main_module
import ast2python.distribution as distribution_module
import ast2python.lowering_matrix as lowering_matrix_pkg
import ast2python.quality as quality_module
import ast2python.translator as translator_module
from ast2python.ast.schema import ASTNode, ASTProgram, ensure_program_node, validate_ast
from ast2python.binder import bind_builtin_call
from ast2python.binder_model import TypeInfo
from ast2python.cli.commands import (
    command_coverage,
    command_lowering_matrix,
    command_source_map_contract,
)
from ast2python.context import TranslationContext
from ast2python.diagnostics import SourceLocation
from ast2python.distribution import distribution_manifest
from ast2python.emitters.inputs import PineInputEmitter
from ast2python.emitters.time import PineTimeEmitter, _timezone_for_name
from ast2python.errors import (
    NameCollisionError,
    TypeResolutionError,
    UnsupportedBuiltinError,
    UnsupportedNodeError,
    ValidationError,
)
from ast2python.lowering_matrix.loader import load_lowering_entries
from ast2python.lowering_matrix.validate import (
    LoweringMatrixError,
    validate_lowering_matrix_payload,
)
from ast2python.naming import NamingRegistry
from ast2python.profiles import CompileProfile
from ast2python.quality import duplicate_report
from ast2python.runtime_contract.generated_base import GeneratedIndicatorBase
from ast2python.translator import Translator
from ast2python.translator_mixins.metadata_declarations import (
    collect_declaration_metadata,
    extract_declaration_title,
)
from ast2python.translator_mixins.metadata_globals import collect_globals
from ast2python.translator_mixins.metadata_inputs import build_input_metadata
from ast2python.translator_mixins.metadata_requests import (
    diagnose_request_security_captures,
    diagnose_request_security_lower_tf_safety,
    is_lower_tf_safe_immutable_scalar_capture,
)
from ast2python.translator_parts.validation import TranslatorValidationMixin
from ast2python.types import make_type_info
from tests.contract_metadata import with_valid_producer_metadata

pytestmark = pytest.mark.filterwarnings("ignore:.*found in sys.modules.*:RuntimeWarning")


def ident(name: str, *, kind: str = "Identifier") -> dict[str, Any]:
    return {"kind": kind, "name": name}


def lit(value: Any, literal_type: str = "int") -> dict[str, Any]:
    return {"kind": "Literal", "literal_type": literal_type, "value": value}


def arg(value: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    return {"kind": "Argument", "name": name, "value": value}


def member(
    obj: str | dict[str, Any], name: str, *, kind: str = "MemberAccessExpr"
) -> dict[str, Any]:
    return {"kind": kind, "object": ident(obj) if isinstance(obj, str) else obj, "member": name}


def call(callee: str | dict[str, Any], args: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "kind": "CallExpr",
        "callee": ident(callee) if isinstance(callee, str) else callee,
        "arguments": args or [],
    }


def legacy_call(
    callee: str | dict[str, Any], args: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "kind": "Call",
        "callee": ident(callee) if isinstance(callee, str) else callee,
        "arguments": args or [],
    }


def program_with(
    items: list[dict[str, Any]] | None = None, *, diagnostics: list[Any] | None = None
) -> dict[str, Any]:
    payload = {
        "kind": "Program",
        "language": "pine",
        "version": 6,
        "declaration": {
            "kind": "DeclarationStatement",
            "script_type": "indicator",
            "call": call("indicator", [arg(lit("Coverage 100", "string"))]),
        },
        "items": items or [],
    }
    if diagnostics is not None:
        payload["diagnostics"] = diagnostics
    return with_valid_producer_metadata(payload)


def test_lazy_exports_and_module_entrypoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert binder_signatures.__getattr__("BUILTIN_SIGNATURES")
    with pytest.raises(AttributeError):
        binder_signatures.__getattr__("missing")
    with pytest.raises(AttributeError):
        lowering_matrix_pkg.__getattr__("missing")

    monkeypatch.setattr(sys, "argv", ["ast2python", "lowering-matrix", "validate"])
    with pytest.raises(SystemExit) as cli_exit:
        runpy.run_module("ast2python.cli.main", run_name="__main__")
    assert cli_exit.value.code == 0

    repo = tmp_path / "repo"
    (repo / "ast2python").mkdir(parents=True)
    (repo / "ast2python" / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ast2python.distribution", "manifest", "--root", str(repo)])
    with pytest.raises(SystemExit) as dist_exit:
        runpy.run_module("ast2python.distribution", run_name="__main__")
    assert dist_exit.value.code == 0

    monkeypatch.setattr(sys, "argv", ["ast2python.quality", "architecture", str(repo)])
    with pytest.raises(SystemExit) as quality_exit:
        runpy.run_module("ast2python.quality", run_name="__main__")
    assert quality_exit.value.code == 0

    monkeypatch.setattr(sys, "argv", ["ast2python.release", "--root", str(repo)])
    with pytest.raises(SystemExit):
        runpy.run_module("ast2python.release", run_name="__main__")

    monkeypatch.setattr(sys, "argv", ["validate"])
    with pytest.raises(SystemExit) as validate_exit:
        runpy.run_module("ast2python.lowering_matrix.validate", run_name="__main__")
    assert validate_exit.value.code == 0


def test_cli_error_branches_and_smoke_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def raise_matrix() -> None:
        raise LoweringMatrixError("matrix boom")

    monkeypatch.setattr(cli_commands, "validate_lowering_matrix", raise_matrix)
    assert command_lowering_matrix("validate", output=str(tmp_path / "m.md")) == 1
    monkeypatch.setattr(cli_commands, "validate_source_map_contract", raise_matrix)
    assert command_source_map_contract("validate", output=str(tmp_path / "s.md")) == 1
    assert "boom" in capsys.readouterr().err

    ast_path = tmp_path / "unsupported.json"
    ast_path.write_text(
        json.dumps(program_with([{"kind": "UnsupportedStatement"}])),
        encoding="utf-8",
    )
    assert command_coverage(str(ast_path), strict=False) == 0
    assert command_coverage(str(ast_path), strict=True) == 1

    generated = tmp_path / "generated.py"
    generated.write_text(
        "class GeneratedIndicator:\n"
        "    def __init__(self, params=None, runtime=None): pass\n"
        "    def run(self, bars): return list(bars)\n",
        encoding="utf-8",
    )
    assert cli_main_module.main(["smoke", str(generated)]) == 0

    fake_parser = SimpleNamespace(parse_args=lambda _argv=None: SimpleNamespace(command="noop"))
    monkeypatch.setattr(cli_main_module, "build_parser", lambda: fake_parser)
    assert cli_main_module.main(["noop"]) == 0

    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError):
        cli_commands._load_generated_class(generated)


def test_small_defensive_helpers_and_quality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class KindlessProgram:
        def field(self, *_args: Any, **_kwargs: Any) -> Any:
            return "pine"

        @property
        def declaration(self) -> ASTNode:
            return ASTNode({"kind": "DeclarationStatement"})

        def descendants(self) -> list[Any]:
            return [SimpleNamespace(kind="")]

    assert "Node kind/type is required" in validate_ast(KindlessProgram())[0]  # type: ignore[arg-type]
    assert (
        ASTNode({"kind": "Parent", "child": {"kind": "Child"}}).children("child")[0].kind == "Child"
    )
    assert SourceLocation().source_map is None

    ctx = TranslationContext()
    first = ctx.declare_var(
        "x",
        type_ref="float",
        qualifier="series",
        declaration_kind="normal",
        is_series=True,
        is_mutable=True,
        loc=None,
    )
    second = ctx.declare_var(
        "x",
        type_ref="int",
        qualifier="const",
        declaration_kind="normal",
        is_series=False,
        is_mutable=False,
        loc=None,
    )
    assert second is first
    with pytest.raises(UnsupportedNodeError):
        ctx.unsupported("BadNode", "no lowering")

    root = tmp_path / "quality"
    (root / "ok").mkdir(parents=True)
    (root / "ok" / "a.py").write_text(
        'def empty():\n    """doc"""\n\n'
        "def only_pass():\n    pass\n\n"
        "def only_ellipsis():\n    ...\n\n"
        "def only_raise():\n    raise RuntimeError()\n",
        encoding="utf-8",
    )
    (root / ".venv").mkdir()
    (root / ".venv" / "ignored.py").write_text("def ignored():\n    return 1\n", encoding="utf-8")
    (root / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    assert duplicate_report(root).duplicate_group_count == 0

    monkeypatch.setattr(
        quality_module.argparse.ArgumentParser,
        "parse_args",
        lambda self, argv=None: SimpleNamespace(command="unknown"),
    )
    assert quality_module.main(["unknown"]) == 2

    collision = NamingRegistry()
    collision.used = {"value", *(f"value_{i}" for i in range(2, 10002))}
    with pytest.raises(NameCollisionError):
        collision.reserve("value")
    naming = NamingRegistry()
    assert naming.discard_name() == "_discard_1"
    naming.reset_discards()
    assert naming.discard_name() == "_discard_1"

    with pytest.raises(ValueError):
        CompileProfile.from_options("unknown")  # type: ignore[arg-type]

    untyped = TypeInfo("object", "simple", origin="untyped_param")
    assert bind_builtin_call("math.max", [(None, untyped)])
    assert bind_builtin_call("ta.sar", [(None, untyped)])


def test_distribution_hygiene_suffix_and_unreachable_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    (root / "ast2python").mkdir(parents=True)
    (root / "ast2python" / "__init__.py").write_text("", encoding="utf-8")
    (root / "cache.pyc").write_bytes(b"cache")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "cache.txt").write_text("cache", encoding="utf-8")
    assert distribution_manifest(root).hygiene_ok is True
    monkeypatch.setattr(distribution_module, "_is_excluded", lambda _path: False)
    manifest = distribution_manifest(root)
    assert manifest.hygiene_ok is False
    assert "__pycache__/cache.txt" in manifest.violations

    monkeypatch.setattr(
        distribution_module.argparse.ArgumentParser,
        "parse_args",
        lambda self, argv=None: SimpleNamespace(command="unknown"),
    )
    assert distribution_module.main(["unknown"]) == 2


def test_input_and_time_emitters_remaining_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    tr = Translator(compile_profile="diagnostic")
    input_emitter = PineInputEmitter(tr)
    with pytest.raises(UnsupportedBuiltinError):
        input_emitter.translate_runtime_lookup(ASTNode(call(member("input", "int"), [])))
    assert input_emitter.translate_runtime_lookup(
        ASTNode(
            call(
                member("input", "int"),
                [arg({"kind": "BinaryExpr", "op": "+", "left": lit(1), "right": lit(2)})],
            )
        )
    ).startswith("pine_add")
    with pytest.raises(UnsupportedBuiltinError):
        input_emitter.build_metadata(
            ASTNode({"kind": "VarDeclaration", "name": "bad"}),
            ASTNode(call({"kind": "Unknown"}, [arg(lit(1))])),
            "bad",
        )
    metadata = input_emitter.build_metadata(
        ASTNode({"kind": "VarDeclaration", "name": "length"}),
        ASTNode(
            call(
                member("input", "int"),
                [
                    arg(lit(14)),
                    arg(lit("Length", "string")),
                    arg(lit(99), "defval"),
                    arg(lit("Group", "string"), "group"),
                ],
            )
        ),
        "length",
    )
    assert metadata["public"]["group"] == "Group"
    assert metadata["default_python"] == "14"

    time_emitter = PineTimeEmitter(tr)
    with pytest.raises(UnsupportedBuiltinError):
        time_emitter.translate_timestamp_call(
            ASTNode(call("timestamp", [arg(lit(123)), arg(lit(2024))]))
        )

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "zoneinfo":
            raise ImportError("missing zoneinfo")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(UnsupportedBuiltinError):
        _timezone_for_name("Europe/Paris")


def test_loading_validation_and_generated_snapshot(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(
        json.dumps(
            {
                "schema_version": "pine.ast2python.lowering_matrix.v1",
                "runtime_contract": "1.4",
                "entries": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_lowering_entries(matrix_path)

    def no_fail(_errors: list[str]) -> None:
        return None

    import ast2python.lowering_matrix.validate as validate_module

    original_fail = validate_module._fail
    validate_module._fail = no_fail
    try:
        validate_lowering_matrix_payload(
            {
                "schema_version": "pine.ast2python.lowering_matrix.v1",
                "runtime_contract": "1.4",
                "entries": [],
            }
        )
    finally:
        validate_module._fail = original_fail

    class MinimalGenerated(GeneratedIndicatorBase):
        def _process_bar(self, bar: Any) -> None:
            self.last_bar = bar

        def run(self, bars: Any) -> list[Any]:
            return list(bars)

    assert MinimalGenerated()._snapshot() == {}


def test_translator_profile_and_missing_declaration(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="unsupported compile profile"):
        Translator(compile_profile="unknown")  # type: ignore[arg-type]

    class NoDeclProgram(ASTProgram):
        @property
        def declaration(self) -> None:
            return None

        def descendants(self) -> list[ASTNode]:
            return []

    monkeypatch.setattr(translator_module, "validate_ast", lambda _program: [])
    monkeypatch.setattr(Translator, "_enforce_frontend_contract", lambda self, program: None)
    with pytest.raises(ValidationError, match="Program declaration"):
        Translator(compile_profile="diagnostic").translate_program(
            NoDeclProgram({"kind": "Program"})
        )


def test_metadata_declaration_global_and_legacy_helpers() -> None:
    tr = Translator(compile_profile="diagnostic")
    assert (
        extract_declaration_title(
            tr,
            ASTNode(
                {
                    "kind": "DeclarationStatement",
                    "call": call("indicator", [arg(ident("not_literal"))]),
                }
            ),
        )
        == "Generated"
    )
    collect_declaration_metadata(tr, ASTNode({"kind": "DeclarationStatement"}), {})

    info_program = ensure_program_node(
        program_with(
            [
                {"kind": "TupleDeclaration", "targets": ["_", "kept"], "initializer": lit(1)},
                {
                    "kind": "VarDeclaration",
                    "name": "ln",
                    "type_ref": {"kind": "TypeRef", "name": "line"},
                },
            ]
        )
    )
    collect_globals(tr, info_program)
    assert any(key.endswith(":ln") for key in tr.ctx.type_metadata)
    assert any(key.endswith(":kept") for key in tr.ctx.type_metadata)

    legacy = build_input_metadata(
        ASTNode({"kind": "VarDeclaration", "name": "len"}),
        ASTNode(
            call(
                member("input", "float"),
                [
                    arg(lit(1.0, "float")),
                    arg(ident("min_expr"), "minval"),
                    arg(ident("max_expr"), "maxval"),
                    arg(ident("step_expr"), "step"),
                ],
            )
        ),
        "len",
    )
    assert legacy["public"]["default"] == 1.0


def test_metadata_request_helper_edges() -> None:
    class DummyInfo:
        declaration_kind = "normal"
        is_series = True
        type_info = make_type_info("float", "const")

    assert is_lower_tf_safe_immutable_scalar_capture(DummyInfo())

    tr = Translator(compile_profile="diagnostic")
    tr.ctx.declare_var(
        "series_var",
        type_ref="float",
        qualifier="series",
        declaration_kind="normal",
        is_series=True,
        is_mutable=True,
        loc=None,
    )
    diagnose_request_security_lower_tf_safety(tr, ASTNode(ident("unknown")))
    diagnose_request_security_lower_tf_safety(tr, ASTNode(ident("series_var")))
    assert tr.ctx.diagnostics[-1].code
    diagnose_request_security_lower_tf_safety(
        tr,
        ASTNode(
            {
                "kind": "BinaryExpr",
                "op": "+",
                "left": ident("series_var"),
                "right": lit(1),
            }
        ),
    )

    tr2 = Translator(compile_profile="diagnostic")
    diagnose_request_security_captures(
        tr2,
        ASTNode(call(member("request", "security"), [arg(call(member("request", "financial")))])),
    )
    assert tr2.ctx.diagnostics[-1].severity.value == "warning"


def test_type_inference_unreachable_legacy_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    tr = Translator(compile_profile="diagnostic")
    info = tr.ctx.declare_var(
        "declared_only",
        type_ref="int",
        qualifier="simple",
        declaration_kind="normal",
        is_series=False,
        is_mutable=False,
        loc=None,
    )
    info.type_info = None
    assert tr._infer_type_info(ASTNode(ident("declared_only"))).base_type == "int"
    assert (
        tr._infer_type_info(ASTNode(legacy_call("time", [arg(lit("D", "string"))]))).base_type
        == "int"
    )
    assert tr._infer_type_info(ASTNode(call(lit(None, "na"), []))).base_type == "bool"

    monkeypatch.setattr(tr, "_is_input_call", lambda _node: False)
    for raw, expected in [
        (call(member("input", "bool"), []), "bool"),
        (call(member("input", "int"), []), "int"),
        (call(member("input", "string"), []), "string"),
        (call(member("input", "timeframe"), []), "string"),
        (call(member("input", "session"), []), "string"),
        (call(member("input", "time"), []), "int"),
        (call(member("input", "source"), []), "float"),
    ]:
        assert tr._infer_type_info(ASTNode(raw)).base_type == expected
    monkeypatch.setattr(tr, "_is_input_call", lambda _node: True)
    assert (
        tr._infer_type_info(ASTNode({"kind": "CallExpr", "callee": {"kind": "Unknown"}})).base_type
        == "object"
    )


def test_call_and_expression_remaining_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    tr = Translator(compile_profile="diagnostic", allow_external_library_stubs=True)
    assert (
        tr._translate_user_func_arg(ASTNode(ident("close")), runtime_expr="self.rt")
        == "self.rt.close"
    )
    tr.functions.add("foo")
    import ast2python.translator_parts.calls as calls_module

    original_member_chain = calls_module.member_chain
    monkeypatch.setattr(
        calls_module,
        "member_chain",
        lambda node: None if node.kind == "Identifier" else original_member_chain(node),
    )
    assert tr._translate_call(ASTNode(call("foo", [])), runtime_expr="self.rt").startswith(
        "self.foo"
    )
    monkeypatch.setattr(calls_module, "member_chain", original_member_chain)

    monkeypatch.setattr(tr, "_bind_or_raise", lambda _name, _node: None)
    security = ASTNode(
        call(
            member("request", "security"),
            [arg(lit("A", "string")), arg(lit("D", "string")), arg(ident("close")), arg(lit(1))],
        )
    )
    assert "request_security" in tr._translate_request_security(security, runtime_expr="self.rt")
    lower_tf = ASTNode(
        call(
            member("request", "security_lower_tf"),
            [arg(lit("A", "string")), arg(lit("1", "string")), arg(ident("close")), arg(lit(1))],
        )
    )
    assert "request_security_lower_tf" in tr._translate_request_security_lower_tf(
        lower_tf, runtime_expr="self.rt"
    )

    monkeypatch.setattr(tr, "_ordered_call_arguments", lambda _name, node: tr._call_arguments(node))
    assert tr._translate_reference_call(
        "array.custom",
        ASTNode(call(member("array", "custom"), [arg(lit(1)), arg(lit(0))])),
        runtime_expr="self.rt",
    ).startswith("PineArray.custom")

    tr_bad = Translator(compile_profile="diagnostic")
    monkeypatch.setenv("DEBUG_BIND", "1")
    with pytest.raises(TypeResolutionError):
        tr_bad._bind_or_raise(
            "math.sqrt", ASTNode(call(member("math", "sqrt"), [arg(lit("x", "string"))]))
        )
    monkeypatch.delenv("DEBUG_BIND", raising=False)

    assert tr._translate_series_source_argument(ASTNode(lit(1)), runtime_expr="self.rt") == "1"
    assert "hlc3_series" in tr._translate_ta_call(
        "ta.ema",
        ASTNode(
            call(
                member("ta", "ema"),
                [
                    arg(legacy_call(member("ta", "hlc3", kind="MemberAccess"), [])),
                    arg(lit(9)),
                ],
            )
        ),
        runtime_expr="self.rt",
    )

    assert (
        tr._translate_member_access(ASTNode(member("array", "size")), runtime_expr="self.rt")
        == "PineArray.size"
    )
    assert tr._translate_scalar_operand(ASTNode(lit(7)), runtime_expr="self.rt") == "7"
    assert (
        tr.translate_expression(
            ASTNode(
                {
                    "kind": "BinaryExpr",
                    "op": "==",
                    "left": lit("same", "string"),
                    "right": lit("same", "string"),
                }
            )
        )
        == "('same' == 'same')"
    )

    import ast2python.translator_parts.expressions as expressions_module

    original_expression_member_chain = expressions_module.member_chain
    monkeypatch.setattr(expressions_module, "member_chain", lambda _node: "custom.chain")
    try:
        assert (
            tr._translate_member_access(
                ASTNode({"kind": "MemberAccessExpr"}), runtime_expr="self.rt"
            )
            == "custom.chain"
        )
    finally:
        monkeypatch.setattr(expressions_module, "member_chain", original_expression_member_chain)

    original_translate = tr.translate_expression
    original_infer = tr._infer_type_info

    def translate_empty_string_probe(node: ASTNode, *, runtime_expr: str = "self.rt") -> str:
        if node.kind == "CoverageProbe":
            return '""'
        return original_translate(node, runtime_expr=runtime_expr)

    monkeypatch.setattr(tr, "translate_expression", translate_empty_string_probe)
    monkeypatch.setattr(
        tr,
        "_infer_type_info",
        lambda node: (
            make_type_info("object", "series")
            if node.kind == "CoverageProbe"
            else original_infer(node)
        ),
    )
    empty_probe = {"kind": "CoverageProbe"}
    assert (
        original_translate(
            ASTNode({"kind": "BinaryExpr", "op": "==", "left": empty_probe, "right": empty_probe})
        )
        == '("" == "")'
    )
    monkeypatch.setattr(tr, "translate_expression", original_translate)
    monkeypatch.setattr(tr, "_infer_type_info", original_infer)
    switch = ASTNode(
        {
            "kind": "SwitchStructure",
            "cases": [
                {
                    "kind": "SwitchCase",
                    "condition": lit(True, "bool"),
                    "block": {
                        "kind": "Block",
                        "statements": [{"kind": "ExpressionStatement", "expression": lit(1)}],
                    },
                },
                {"kind": "SwitchCase", "default": True, "block": lit(2)},
            ],
        }
    )
    assert "pine_bool" in tr.translate_expression(switch)
    assert (
        tr._block_expression(ASTNode({"kind": "Block", "statements": []}), runtime_expr="self.rt")
        is None
    )
    assert (
        tr._block_expression(
            ASTNode({"kind": "Block", "statements": [{"kind": "ExpressionStatement"}]}),
            runtime_expr="self.rt",
        )
        is None
    )
    tr._reject_visual_value(None)


def test_active_metadata_lower_tf_edges() -> None:
    tr = Translator(compile_profile="diagnostic")
    with pytest.raises(UnsupportedBuiltinError):
        tr._diagnose_request_security_lower_tf_safety(
            ASTNode(call(member("request", "financial"), []))
        )
    with pytest.raises(UnsupportedBuiltinError):
        tr._diagnose_request_security_lower_tf_safety(ASTNode(call(member("ta", "ema"), [])))

    safe_local = tr.ctx.declare_var(
        "safe_local",
        type_ref="float",
        qualifier="series",
        declaration_kind="normal",
        is_series=False,
        is_mutable=False,
        loc=None,
    )
    safe_local.type_info = make_type_info("float", "series")
    assert tr._is_lower_tf_safe_immutable_scalar_capture(safe_local) is True

    input_missing_type = tr.ctx.declare_var(
        "input_missing_type",
        type_ref="float",
        qualifier="input",
        declaration_kind="input",
        is_series=True,
        is_mutable=False,
        loc=None,
    )
    input_missing_type.type_info = None
    assert tr._is_lower_tf_safe_immutable_scalar_capture(input_missing_type) is False

    tr._diagnose_request_security_lower_tf_safety(ASTNode(ident("unknown_name")))


def test_declarations_statements_and_validation_remaining_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tr = Translator(
        compile_profile="diagnostic", allow_invalid_ast=True, allow_realtime_local_simulation=True
    )
    tr._emit_udt_declaration(ASTNode({"kind": "TypeDeclaration", "name": "Empty"}))
    tr._emit_enum_declaration(ASTNode({"kind": "EnumDeclaration", "name": "EmptyEnum"}))
    tr._emit_function_declaration(
        ASTNode({"kind": "FunctionDeclaration", "name": "f", "body": lit(1)})
    )
    tr._emit_function_declaration(
        ASTNode(
            {
                "kind": "FunctionDeclaration",
                "name": "g",
                "body": {
                    "kind": "Block",
                    "statements": [
                        {"kind": "VarDeclaration", "name": "x", "initializer": lit(1)},
                        {"kind": "ExpressionStatement", "expression": ident("x")},
                    ],
                },
            }
        )
    )

    tr._resolve_or_declare_var(
        ASTNode(
            {
                "kind": "VarDeclaration",
                "name": "obj",
                "type_ref": {"kind": "TypeRef", "name": "line"},
            }
        ),
        "obj",
    )
    tr._emit_tuple_declaration(
        ASTNode(
            {
                "kind": "TupleDeclaration",
                "targets": ["local"],
                "initializer": {"kind": "TupleExpr", "items": [lit(1)]},
            }
        )
    )

    tr.ctx.enter_scope("block")
    try:
        tr._emit_tuple_declaration(
            ASTNode(
                {
                    "kind": "TupleDeclaration",
                    "targets": ["local_only"],
                    "initializer": {"kind": "TupleExpr", "items": [lit(1)]},
                }
            )
        )
    finally:
        tr.ctx.exit_scope()

    tr._bind_or_raise = lambda _name, _node: None  # type: ignore[method-assign]
    tr._emit_tuple_declaration(
        ASTNode(
            {
                "kind": "TupleDeclaration",
                "targets": ["bb_mid", "bb_upper", "bb_lower"],
                "initializer": call(
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
            }
        )
    )
    tr._emit_reassignment(
        ASTNode({"kind": "Reassignment", "target": ident("local"), "op": ":=", "value": lit(2)})
    )
    varip = tr.ctx.declare_var(
        "persist",
        type_ref="float",
        qualifier="series",
        declaration_kind="varip",
        is_series=False,
        is_mutable=True,
        loc=None,
        prefer_py_name="persist",
    )
    varip.type_info = make_type_info("float", "series")
    tr._emit_reassignment(
        ASTNode({"kind": "Reassignment", "target": ident("persist"), "op": "=", "value": lit(3)})
    )
    tr._emit_statement(
        ASTNode(
            {
                "kind": "ForInStructure",
                "target": ident("item"),
                "iterable": {"kind": "ArrayLiteral", "items": [lit(1)]},
                "body": {"kind": "Block", "statements": []},
            }
        )
    )
    assert tr._switch_cases(ASTNode({"kind": "SwitchStructure", "cases": []})) == []
    case = ASTNode({"kind": "SwitchCase", "value": lit(1), "body": {"kind": "Block"}})
    assert tr._case_condition(case) is not None
    assert tr._case_body(case) is not None

    assert (
        TranslatorValidationMixin._strategy_calc_on_every_tick_enabled(
            tr, ASTNode({"kind": "DeclarationStatement"})
        )
        is False
    )
    original_translate_expression = tr.translate_expression
    tr.translate_expression = lambda node, runtime_expr="self.rt": "False"  # type: ignore[method-assign]
    assert (
        TranslatorValidationMixin._strategy_calc_on_every_tick_enabled(
            tr,
            ASTNode(
                {
                    "kind": "DeclarationStatement",
                    "call": call("strategy", [arg(ident("enabled"), "calc_on_every_tick")]),
                }
            ),
        )
        is False
    )
    tr.translate_expression = original_translate_expression  # type: ignore[method-assign]
    assert (
        TranslatorValidationMixin._strategy_calc_on_every_tick_enabled(
            tr,
            ASTNode(
                {
                    "kind": "DeclarationStatement",
                    "call": call("strategy", [arg(lit(True, "bool"), "calc_on_every_tick")]),
                }
            ),
        )
        is True
    )
    TranslatorValidationMixin._enforce_frontend_contract(
        tr,
        ensure_program_node(
            program_with(diagnostics=["ignored", {"severity": "warning", "message": "warn"}])
        ),
    )


def test_module_import_dynamic_none_and_derived_call() -> None:
    tr = Translator(compile_profile="diagnostic")
    tr._declare_dynamic_imports(
        ensure_program_node(
            program_with(
                [
                    {"kind": "CallExpr", "callee": {"kind": "Unknown"}, "arguments": []},
                    {"kind": "CallExpr", "callee": member("ta", "hlc3"), "arguments": []},
                ]
            )
        )
    )
    imports_text = "\n".join(tr.ctx.imports.render())
    assert "hlc3_series" in imports_text
