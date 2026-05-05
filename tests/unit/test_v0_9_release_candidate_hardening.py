from __future__ import annotations

import json
import time
from pathlib import Path

import ast2python
from ast2python.ast.schema import load_ast
from ast2python.translator import TranslationResult, Translator, translate_ast
from ast2python.version import __version__
from tests.contract_metadata import with_valid_producer_metadata

FIXTURE = Path(
    "[local-home]/pine2ast/tests/fixtures/golden_ast/valid/real_world_smoke/01_ma_indicator.ast.json"
)


def test_v0_9_public_api_is_explicit_and_semver_aligned() -> None:
    assert ast2python.__all__ == [
        "RUNTIME_CONTRACT_VERSION",
        "TranslationResult",
        "Translator",
        "__version__",
        "translate_ast",
    ]
    assert ast2python.__version__ == __version__ == "2.17.0"
    assert ast2python.Translator is Translator
    assert ast2python.TranslationResult is TranslationResult
    assert ast2python.translate_ast is translate_ast


def test_v0_9_source_map_and_report_audit_fields_are_complete() -> None:
    result = translate_ast(with_valid_producer_metadata(load_ast(FIXTURE)), module_name="audit_ma")
    assert result.metadata["generator_milestone"] == f"v{__version__}"
    assert result.metadata["source_map_file"]
    assert result.metadata["module_name"] == "audit_ma"
    assert result.metadata["class_name"] == "GeneratedIndicator"
    assert result.source_map
    assert all("python_line" in item and "pine_line" in item for item in result.source_map)
    assert result.coverage["source_map_executable_line_ratio"] >= 0.95
    assert "generation_ratio" in result.coverage
    assert 0.0 <= result.coverage["generation_ratio"] <= 1.0


def test_v0_9_translation_performance_smoke() -> None:
    program = with_valid_producer_metadata(load_ast(FIXTURE))
    started = time.perf_counter()
    for _ in range(5):
        result = translate_ast(program, module_name="perf_ma")
        compile(result.code, "perf_ma.py", "exec")
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0


def test_v0_9_release_manifest_has_current_archive_and_docs() -> None:
    manifest = json.loads(Path("RELEASE_MANIFEST_v1.0.0.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.0.0"
    assert manifest["archive"] == "dist/ast2python_v1_0_0.zip"
    assert "docs/LIMITATIONS_v1.0.0.md" in manifest["include"]
    assert "docs/SOURCE_MAP_AUDIT_v1.0.0.md" in manifest["include"]
