from __future__ import annotations

import json
from pathlib import Path

from ast2python.cli.commands import command_translate_many
from ast2python.distribution import distribution_manifest, iter_distribution_files
from ast2python.version import __version__


def test_distribution_excludes_local_build_and_cache_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "ast2python").mkdir(parents=True)
    (root / "ast2python" / "__init__.py").write_text("", encoding="utf-8")
    (root / "ast2python.egg-info").mkdir()
    (root / "ast2python.egg-info" / "SOURCES.txt").write_text("generated", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"cache")
    (root / ".coverage").write_text("coverage", encoding="utf-8")
    (root / f"ast2python-{__version__}.zip").write_bytes(b"zip")

    files = {path.relative_to(root).as_posix() for path in iter_distribution_files(root)}
    assert "ast2python/__init__.py" in files
    assert "ast2python.egg-info/SOURCES.txt" not in files
    assert "__pycache__/x.pyc" not in files
    assert ".coverage" not in files
    assert f"ast2python-{__version__}.zip" not in files
    assert distribution_manifest(root).hygiene_ok is True


def test_translate_many_returns_nonzero_when_diagnostic_output_contains_error(
    tmp_path: Path,
) -> None:
    ast_path = tmp_path / "unsafe.json"
    ast_path.write_text(
        json.dumps(
            {
                "kind": "Program",
                "language": "pine",
                "version": 6,
                "producer_metadata": {
                    "contract": "pine.ast_contract.v1",
                    "producer": {"name": "pine2ast", "version": "4.0.0"},
                    "schema_version": "1.0",
                    "pine_language_version": 6,
                    "runtime_contract_profile": "v1.4",
                    "runtime_contract": "runtime_contract_v1_4",
                    "parser_gate": "pass",
                    "semantic_gate": "pass",
                },
                "diagnostics": [{"severity": "ERROR", "code": "P2A9999", "message": "boom"}],
                "declaration": {
                    "kind": "DeclarationStatement",
                    "script_type": "indicator",
                    "call": {
                        "kind": "CallExpr",
                        "callee": {"kind": "Identifier", "name": "indicator"},
                        "arguments": [
                            {
                                "kind": "Argument",
                                "value": {
                                    "kind": "Literal",
                                    "literal_type": "string",
                                    "value": "x",
                                },
                            }
                        ],
                    },
                },
                "items": [],
            }
        ),
        encoding="utf-8",
    )
    status = command_translate_many(
        [str(ast_path)],
        str(tmp_path / "out"),
        compile_profile="diagnostic",
        allow_invalid_ast=True,
        strict=False,
        emit_source_comments=True,
    )
    assert status == 1
