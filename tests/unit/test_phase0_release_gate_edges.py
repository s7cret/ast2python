from __future__ import annotations

import builtins
import copy
import json
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


def test_pine2ast_dependency_is_an_exact_rc3_wheel_requirement() -> None:
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    dependency = next(
        item for item in config["project"]["dependencies"] if item.startswith("pine2ast")
    )
    assert dependency == "pine2ast==5.0.0rc3"


def test_pinelib_dependency_is_an_exact_rc3_wheel_requirement() -> None:
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    dependency = next(
        item for item in config["project"]["dependencies"] if item.startswith("pinelib")
    )
    assert dependency == "pinelib==5.0.0rc3"


def test_release_dependencies_do_not_use_vcs_urls() -> None:
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert all("git+" not in item for item in config["project"]["dependencies"])


def test_ci_sibling_checkouts_are_immutable_and_wheel_smoke_is_isolated() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    wheel_smoke = (root / "scripts/wheel_smoke.sh").read_text(encoding="utf-8")

    refs = [line.split(":", 1)[1].strip() for line in workflow.splitlines() if "ref:" in line]
    assert len(refs) == 3
    assert all(len(ref) == 40 and set(ref) <= set("0123456789abcdef") for ref in refs)
    assert "bash scripts/wheel_smoke.sh" in workflow
    assert "pip wheel" not in wheel_smoke
    assert "--no-build-isolation" not in wheel_smoke
    assert "python -I" in wheel_smoke or '"$VENV_PY" -I' in wheel_smoke
    assert "--outdir" in wheel_smoke


def test_cross_layer_release_catalog_rejects_every_malformed_evidence_shape(
    tmp_path: Path,
) -> None:
    from ast2python.release import _cross_layer_catalog_status

    real_root = Path(__file__).resolve().parents[2]
    valid_catalog = json.loads(
        (real_root / "ast2python/lowering_matrix/cross_layer_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    valid_manifest = json.loads(
        (real_root / "tests/integration/canonical_phase1_corpus.json").read_text(encoding="utf-8")
    )
    root = tmp_path / "repo"
    catalog_path = root / "ast2python/lowering_matrix/cross_layer_catalog.json"
    manifest_path = root / "tests/integration/canonical_phase1_corpus.json"
    evidence_test = root / "tests/integration/test_phase1_canonical_corpus.py"
    catalog_path.parent.mkdir(parents=True)
    manifest_path.parent.mkdir(parents=True)
    evidence_test.write_text("# evidence\n", encoding="utf-8")

    def write_catalog(payload: object) -> None:
        catalog_path.write_text(json.dumps(payload), encoding="utf-8")

    def write_manifest(payload: object) -> None:
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    write_catalog(valid_catalog)
    write_manifest(valid_manifest)
    assert _cross_layer_catalog_status(root) == (True, 20)

    for malformed_count in ("20", 20.9):
        payload = copy.deepcopy(valid_catalog)
        payload["case_count"] = malformed_count
        write_catalog(payload)
        assert _cross_layer_catalog_status(root)[0] is False
    write_catalog(valid_catalog)
    for malformed_minimum in ("20", 20.9):
        payload = copy.deepcopy(valid_manifest)
        payload["minimum_case_count"] = malformed_minimum
        write_manifest(payload)
        assert _cross_layer_catalog_status(root)[0] is False
    write_manifest(valid_manifest)

    catalog_path.unlink()
    assert _cross_layer_catalog_status(root) == (False, 0)
    write_catalog([])
    assert _cross_layer_catalog_status(root) == (False, 0)

    for source_manifest in ("/tmp/outside.json", "../outside.json"):
        payload = copy.deepcopy(valid_catalog)
        payload["source_manifest"] = source_manifest
        write_catalog(payload)
        assert _cross_layer_catalog_status(root)[0] is False

    payload = copy.deepcopy(valid_catalog)
    payload["evidence"][0] = "bad"
    write_catalog(payload)
    assert _cross_layer_catalog_status(root)[0] is False

    payload = copy.deepcopy(valid_catalog)
    payload["evidence"][0]["layers"] = ["parse"]
    write_catalog(payload)
    assert _cross_layer_catalog_status(root)[0] is False

    payload = copy.deepcopy(valid_catalog)
    payload["evidence"][1]["case_id"] = payload["evidence"][0]["case_id"]
    write_catalog(payload)
    assert _cross_layer_catalog_status(root)[0] is False

    payload = copy.deepcopy(valid_catalog)
    payload["minimum_case_count"] = valid_catalog["minimum_case_count"] + 1
    write_catalog(payload)
    assert _cross_layer_catalog_status(root)[0] is False

    payload = copy.deepcopy(valid_catalog)
    payload["evidence"] = list(reversed(payload["evidence"]))
    write_catalog(payload)
    assert _cross_layer_catalog_status(root)[0] is False

    payload = copy.deepcopy(valid_catalog)
    payload["evidence"][0]["features"] = ["tampered"]
    write_catalog(payload)
    assert _cross_layer_catalog_status(root)[0] is False

    payload = copy.deepcopy(valid_catalog)
    payload["evidence"][0]["unexpected"] = True
    write_catalog(payload)
    assert _cross_layer_catalog_status(root)[0] is False

    write_catalog(valid_catalog)
    malformed_features = copy.deepcopy(valid_manifest)
    malformed_features["cases"][0]["features"] = [""]
    write_manifest(malformed_features)
    assert _cross_layer_catalog_status(root)[0] is False

    write_manifest(valid_manifest)
    write_catalog(valid_catalog)
    write_manifest([])
    assert _cross_layer_catalog_status(root)[0] is False
    manifest_path.write_text("{", encoding="utf-8")
    assert _cross_layer_catalog_status(root)[0] is False
    payload = copy.deepcopy(valid_manifest)
    payload["schema_version"] = "bad"
    write_manifest(payload)
    assert _cross_layer_catalog_status(root)[0] is False


def test_lowering_release_gate_is_truthful_and_rejects_not_started_p0(
    tmp_path: Path,
) -> None:
    from ast2python.release import _lowering_matrix_status

    real_root = Path(__file__).resolve().parents[2]
    source = real_root / "ast2python/lowering_matrix/lowering_matrix.json"
    root = tmp_path / "repo"
    matrix_path = root / "ast2python/lowering_matrix/lowering_matrix.json"
    matrix_path.parent.mkdir(parents=True)
    payload = json.loads(source.read_text(encoding="utf-8"))
    matrix_path.write_text(json.dumps(payload), encoding="utf-8")

    ok, details = _lowering_matrix_status(root)

    assert ok is True
    assert details["scope"] == "verified_lowering_subset"
    assert details["full_pine_v6_coverage_claimed"] is False
    assert details["entry_count"] == len(payload["entries"])
    assert details["lowering_status_summary"]["PARTIAL"] > 0
    assert details["lowering_status_summary"]["UNSUPPORTED_DIAGNOSTIC"] > 0
    assert details["lowering_status_summary"].get("NOT_STARTED", 0) == 0

    payload["entries"][0]["lowering_status"] = "NOT_STARTED"
    matrix_path.write_text(json.dumps(payload), encoding="utf-8")
    assert _lowering_matrix_status(root)[0] is False

    matrix_path.write_text("[]", encoding="utf-8")
    assert _lowering_matrix_status(root)[0] is False

    payload = json.loads(source.read_text(encoding="utf-8"))
    verified_entry = next(
        entry for entry in payload["entries"] if entry["lowering_status"] == "DONE_VERIFIED"
    )
    verified_entry["coverage_status"] = "PARTIAL"
    matrix_path.write_text(json.dumps(payload), encoding="utf-8")
    assert _lowering_matrix_status(root)[0] is False

    verified_entry["coverage_status"] = "DONE_VERIFIED"
    verified_entry["source_map_status"] = "PARTIAL"
    matrix_path.write_text(json.dumps(payload), encoding="utf-8")
    assert _lowering_matrix_status(root)[0] is False


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
