import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ast2python.errors import UnsupportedBuiltinError, ValidationError
from ast2python.profiles import CompileProfile
from ast2python.translator import translate_ast

BASE = {
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
        "script_type": "indicator",
        "call": {
            "kind": "CallExpr",
            "callee": {"kind": "Identifier", "name": "indicator"},
            "arguments": [
                {
                    "kind": "Argument",
                    "name": None,
                    "value": {"kind": "Literal", "literal_type": "string", "value": "x"},
                }
            ],
        },
    },
    "items": [],
}


def program(**updates):
    p = copy.deepcopy(BASE)
    p.update(updates)
    return p


def test_embedded_frontend_error_rejected_by_default():
    p = program(diagnostics=[{"severity": "ERROR", "code": "P2A9999", "message": "boom"}])
    with pytest.raises(ValidationError):
        translate_ast(p, module_name="bad")


def test_allow_invalid_ast_marks_unsafe():
    p = program(diagnostics=[{"severity": "ERROR", "code": "P2A9999", "message": "boom"}])
    result = translate_ast(
        p, module_name="bad", compile_profile="diagnostic", allow_invalid_ast=True
    )
    assert result.metadata["parity_safe"] is False
    assert result.metadata["unsafe"] is True
    assert result.metadata["compile_profile"] == "diagnostic"
    assert any("allow_invalid_ast" in risk for risk in result.metadata["parity_risks"])


def test_missing_and_mismatch_contract_rejected():
    with pytest.raises(ValidationError):
        translate_ast(program(producer_metadata={}), module_name="missing")
    p = program()
    p["producer_metadata"]["runtime_contract"] = "runtime_contract_v9"
    with pytest.raises(ValidationError):
        translate_ast(p, module_name="mismatch")
    p = program()
    p["producer_metadata"].pop("contract")
    with pytest.raises(ValidationError):
        translate_ast(p, module_name="missing_contract")


def test_non_pass_frontend_gates_rejected_and_override_marks_unsafe():
    p = program()
    p["producer_metadata"]["semantic_gate"] = "not_run"
    with pytest.raises(ValidationError):
        translate_ast(p, module_name="gate_bad")
    result = translate_ast(
        p, module_name="gate_override", compile_profile="diagnostic", allow_invalid_ast=True
    )
    assert result.metadata["parity_safe"] is False
    assert any(d["code"] == "P2A_FRONTEND_GATE_BLOCK" for d in result.metadata["diagnostics"])


def test_contract_override_marks_unsafe():
    result = translate_ast(
        program(producer_metadata={}),
        module_name="missing",
        compile_profile="diagnostic",
        allow_contract_mismatch=True,
    )
    assert result.metadata["parity_safe"] is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"allow_invalid_ast": True},
        {"allow_contract_mismatch": True},
        {"allow_external_library_stubs": True},
        {"allow_unsupported_request_stubs": True},
        {"allow_realtime_local_simulation": True},
    ],
)
def test_production_compile_profile_rejects_unsafe_overrides(kwargs):
    with pytest.raises(
        ValidationError, match="production compile profile forbids unsafe overrides"
    ):
        translate_ast(program(), module_name="unsafe", **kwargs)


def test_compile_profile_factories_cover_diagnostic_unsafe_gates():
    diagnostic = CompileProfile.diagnostic(
        allow_external_library_stubs=True,
        allow_unsupported_request_stubs=True,
        allow_invalid_ast=True,
        allow_implicit_version_rewrite=True,
        allow_subprocess_fallback=True,
    )
    assert diagnostic.name == "diagnostic"
    assert diagnostic.allow_implicit_version_rewrite is True
    assert diagnostic.allow_subprocess_fallback is True

    with pytest.raises(ValueError, match="unsafe overrides"):
        CompileProfile.from_options("production", allow_subprocess_fallback=True)


def test_unsupported_request_fails_by_default_and_stub_marks_unsafe():
    p = program(
        items=[
            {
                "kind": "ExpressionStatement",
                "expression": {
                    "kind": "CallExpr",
                    "callee": {
                        "kind": "MemberAccessExpr",
                        "object": {"kind": "Identifier", "name": "request"},
                        "member": "dividends",
                    },
                    "arguments": [],
                },
            }
        ]
    )
    with pytest.raises(UnsupportedBuiltinError):
        translate_ast(p, module_name="request_bad")
    result = translate_ast(
        p,
        module_name="request_stub",
        compile_profile="diagnostic",
        allow_unsupported_request_stubs=True,
    )
    assert result.metadata["parity_safe"] is False
    assert result.metadata["unsafe"] is True
    assert "unsupported_request_stub" in result.metadata["unsupported_features"]


def test_external_import_fails_by_default_and_stub_marks_unsafe():
    p = program(
        items=[
            {
                "kind": "ImportDeclaration",
                "path": "user/lib/1",
                "owner": "user",
                "library": "lib",
                "version": "1",
                "alias": "lib",
            }
        ]
    )
    with pytest.raises(UnsupportedBuiltinError):
        translate_ast(p, module_name="import_bad")
    result = translate_ast(
        p,
        module_name="import_stub",
        compile_profile="diagnostic",
        allow_external_library_stubs=True,
    )
    assert result.metadata["parity_safe"] is False
    assert result.metadata["unsafe"] is True
    assert "external_library_stubs" in result.metadata["unsupported_features"]


def test_calc_on_every_tick_rejected_by_default_and_override_marks_unsafe():
    p = program()
    p["declaration"] = {
        "kind": "DeclarationStatement",
        "script_type": "strategy",
        "call": {
            "kind": "CallExpr",
            "callee": {"kind": "Identifier", "name": "strategy"},
            "arguments": [
                {
                    "kind": "Argument",
                    "name": None,
                    "value": {"kind": "Literal", "literal_type": "string", "value": "rt"},
                },
                {
                    "kind": "Argument",
                    "name": "calc_on_every_tick",
                    "value": {"kind": "Literal", "literal_type": "bool", "value": True},
                },
            ],
        },
    }
    with pytest.raises(ValidationError):
        translate_ast(p, module_name="rt_bad")
    result = translate_ast(
        p,
        module_name="rt_local",
        compile_profile="diagnostic",
        allow_realtime_local_simulation=True,
    )
    assert result.metadata["parity_safe"] is False
    assert "realtime_local_simulation" in result.metadata["unsupported_features"]
    assert any(d["code"] == "P2A_CALC_ON_EVERY_TICK_UNSAFE" for d in result.metadata["diagnostics"])


def test_varip_rejected_by_default_and_override_marks_unsafe():
    p = program(
        items=[
            {
                "kind": "VarDeclaration",
                "mode": "varip",
                "name": "ticks",
                "initializer": {"kind": "Literal", "literal_type": "int", "value": 0},
            }
        ]
    )
    with pytest.raises(ValidationError):
        translate_ast(p, module_name="varip_bad")
    result = translate_ast(
        p,
        module_name="varip_local",
        compile_profile="diagnostic",
        allow_realtime_local_simulation=True,
    )
    assert result.metadata["parity_safe"] is False
    assert "varip_local_simulation" in result.metadata["unsupported_features"]
    assert any(d["code"] == "P2A_VARIP_UNSAFE" for d in result.metadata["diagnostics"])


def test_cli_rejects_error_and_allow_risk_writes_unsafe_metadata(tmp_path):
    p = program(diagnostics=[{"severity": "ERROR", "code": "P2A9999", "message": "boom"}])
    ast_path = tmp_path / "bad.json"
    ast_path.write_text(json.dumps(p), encoding="utf-8")
    out = tmp_path / "out"
    cmd = [sys.executable, "-m", "ast2python.cli.main", "translate", str(ast_path), "-o", str(out)]
    fail = subprocess.run(
        cmd, cwd=Path(__file__).resolve().parents[2], text=True, capture_output=True
    )
    assert fail.returncode != 0
    prod_unsafe = subprocess.run(
        cmd + ["--allow-invalid-ast"],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
    )
    assert prod_unsafe.returncode != 0
    assert "production compile profile forbids unsafe overrides" in prod_unsafe.stderr
    ok = subprocess.run(
        cmd + ["--compile-profile", "diagnostic", "--allow-invalid-ast"],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
    )
    assert ok.returncode == 0, ok.stderr
    metadata = json.loads((out / "bad.meta.json").read_text(encoding="utf-8"))
    assert metadata["parity_safe"] is False
    assert metadata["unsafe"] is True
    assert metadata["compile_profile"] == "diagnostic"
