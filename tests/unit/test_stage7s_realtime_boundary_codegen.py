from __future__ import annotations

import pytest

from ast2python.errors import ValidationError
from ast2python.translator import translate_ast


def _lit(value: object, literal_type: str) -> dict[str, object]:
    return {"kind": "Literal", "literal_type": literal_type, "value": value}


def _program() -> dict[str, object]:
    return {
        "kind": "Program",
        "language": "pine",
        "version": 6,
        "producer_metadata": {
            "contract": "pain.ast_contract.v1",
            "producer": {"name": "pine2ast", "version": "stage7s-test"},
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
                    {
                        "kind": "Argument",
                        "name": None,
                        "value": _lit("Stage7I local realtime skeleton", "string"),
                    },
                    {"kind": "Argument", "name": "calc_on_every_tick", "value": _lit(True, "bool")},
                ],
            },
        },
        "items": [
            {
                "kind": "VarDeclaration",
                "mode": "varip",
                "name": "s3t_varip_tick",
                "initializer": _lit(0, "int"),
            },
        ],
    }


def test_stage7i_realtime_strategy_codegen_rejects_by_default_and_allows_local_simulation_only() -> (
    None
):
    program = _program()
    with pytest.raises(ValidationError):
        translate_ast(program, module_name="stage7i_realtime_default")

    result = translate_ast(
        program,
        module_name="stage7i_realtime_local",
        compile_profile="diagnostic",
        allow_realtime_local_simulation=True,
    )

    assert result.metadata["parity_safe"] is False
    assert "realtime_local_simulation" in result.metadata["unsupported_features"]
    assert "varip_local_simulation" in result.metadata["unsupported_features"]
    assert "calc_on_every_tick=True" in result.code
    assert "get_varip_state" in result.code
    compile(result.code, "stage7i_realtime_local.py", "exec")
