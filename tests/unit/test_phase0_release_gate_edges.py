from __future__ import annotations

import builtins
import tomllib
from pathlib import Path
from typing import Any

import pytest

import ast2python.cli.commands as cli_commands
from ast2python.ast.schema import ASTNode
from ast2python.translator import Translator


def test_mypy_follows_sibling_types_without_reporting_sibling_internals() -> None:
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    sibling_override = next(
        override
        for override in config["tool"]["mypy"]["overrides"]
        if "pinelib" in override["module"]
    )

    assert sibling_override["follow_imports"] == "silent"


def test_cli_smoke_reports_a_clean_skip_when_pinelib_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_import = builtins.__import__

    def fail_pinelib_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pinelib":
            raise ModuleNotFoundError(name)
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(builtins, "__import__", fail_pinelib_import)
        assert cli_commands._ensure_local_pinelib_importable() is False

    generated = tmp_path / "generated.py"
    generated.write_text("class GeneratedIndicator:\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(cli_commands, "_ensure_local_pinelib_importable", lambda: False)

    assert cli_commands.command_smoke(str(generated)) == 0
    assert '"runtime": "skipped"' in capsys.readouterr().out


def test_function_final_declaration_fails_closed_when_symbol_is_not_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translator = Translator()
    function = ASTNode(
        {
            "kind": "FunctionDeclaration",
            "name": "missing_symbol",
            "body": {
                "kind": "Block",
                "statements": [
                    {
                        "kind": "VarDeclaration",
                        "name": "result",
                        "initializer": {"kind": "Literal", "literal_type": "int", "value": 1},
                    }
                ],
            },
        }
    )
    monkeypatch.setattr(translator, "_emit_statement", lambda _node: None)

    translator._emit_function_declaration(function)

    assert "return None" in translator.emitter.render()


def test_previous_bar_rewrite_ignores_non_series_variables() -> None:
    translator = Translator()
    translator.ctx.declare_var(
        "local_value",
        type_ref="float",
        qualifier="simple",
        declaration_kind="normal",
        is_series=False,
        is_mutable=True,
        loc=None,
    )

    expression = "self.local_value.current + 1"
    assert translator._defer_series_reads_to_previous_bar(expression) == expression
