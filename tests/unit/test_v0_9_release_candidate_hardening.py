from __future__ import annotations

import json
import time
from pathlib import Path

import ast2python
from ast2python.ast.schema import load_ast
from ast2python.runtime_contract.generated_base import GeneratedScriptBase
from ast2python.translator import TranslationResult, Translator, translate_ast
from ast2python.version import __version__
from tests.contract_metadata import with_valid_producer_metadata

FIXTURE = Path("tests/fixtures/pine2ast/current_basic_indicator.ast.json")


def test_public_api_is_explicit_and_semver_aligned() -> None:
    assert ast2python.__all__ == [
        "RUNTIME_CONTRACT_VERSION",
        "TranslationResult",
        "CompileProfile",
        "Translator",
        "__version__",
        "translate_ast",
    ]
    assert ast2python.__version__ == __version__ == "4.0.0"
    assert ast2python.Translator is Translator
    assert ast2python.TranslationResult is TranslationResult
    assert ast2python.translate_ast is translate_ast


def test_runtime_contract_base_uses_abstract_methods_not_runtime_stubs() -> None:
    source = Path("ast2python/runtime_contract/generated_base.py").read_text(encoding="utf-8")
    assert "NotImplementedError" not in source
    assert GeneratedScriptBase.__abstractmethods__ == {"run", "_process_bar"}


def test_translator_is_thin_facade_after_refactor() -> None:
    source = Path("ast2python/translator.py").read_text(encoding="utf-8")
    assert len(source.splitlines()) < 220
    assert "TranslatorModuleMixin" in source
    assert "TranslatorStatementMixin" in source
    assert "TranslatorExpressionMixin" in source
    assert "TranslatorCallMixin" in source
    assert "TranslatorValidationMixin" in source
    assert "def _emit_statement" not in source
    assert "def _translate_call" not in source


def test_translator_parts_contain_focused_modules() -> None:
    expected = {
        "shared.py",
        "validation.py",
        "module.py",
        "statements.py",
        "declarations.py",
        "expressions.py",
        "calls.py",
        "metadata.py",
    }
    actual = {path.name for path in Path("ast2python/translator_parts").glob("*.py")}
    assert expected <= actual
    assert (
        max(
            len(path.read_text(encoding="utf-8").splitlines())
            for path in Path("ast2python/translator_parts").glob("*.py")
        )
        < 700
    )


def test_binder_signatures_are_namespace_split() -> None:
    files = {path.name for path in Path("ast2python/binder_signatures").glob("*.py")}
    assert {
        "math.py",
        "ta.py",
        "strategy.py",
        "request.py",
        "array.py",
        "map.py",
        "matrix.py",
    } <= files
    assert len(Path("ast2python/binder.py").read_text(encoding="utf-8").splitlines()) < 250


def test_source_map_and_report_audit_fields_are_complete() -> None:
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


def test_translation_performance_smoke() -> None:
    program = with_valid_producer_metadata(load_ast(FIXTURE))
    started = time.perf_counter()
    for _ in range(5):
        result = translate_ast(program, module_name="perf_ma")
        compile(result.code, "perf_ma.py", "exec")
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0


def test_release_manifest_has_current_archive_and_docs() -> None:
    manifest = json.loads(Path("RELEASE_MANIFEST_v4.0.0.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "4.0.0"
    assert manifest["archive"] == "ast2python-4.0.0.zip"
    assert manifest["contracts"]["ast"] == "pine.ast_contract.v1"
    assert "docs/RELEASE_4_0.md" in manifest["include"]
