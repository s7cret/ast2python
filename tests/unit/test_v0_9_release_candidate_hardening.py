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

FIXTURE = Path(
    "[local-home]/pine2ast/tests/fixtures/golden_ast/valid/real_world_smoke/01_ma_indicator.ast.json"
)


def test_v0_9_public_api_is_explicit_and_semver_aligned() -> None:
    assert ast2python.__all__ == [
        "RUNTIME_CONTRACT_VERSION",
        "TranslationResult",
        "CompileProfile",
        "Translator",
        "__version__",
        "translate_ast",
    ]
    assert ast2python.__version__ == __version__ == "2.17.0"
    assert ast2python.Translator is Translator
    assert ast2python.TranslationResult is TranslationResult
    assert ast2python.translate_ast is translate_ast


def test_runtime_contract_base_uses_abstract_methods_not_runtime_stubs() -> None:
    source = Path("ast2python/runtime_contract/generated_base.py").read_text(encoding="utf-8")

    assert "NotImplementedError" not in source
    assert GeneratedScriptBase.__abstractmethods__ == {"run", "_process_bar"}


def test_translator_delegates_global_collection_to_metadata_helper() -> None:
    source = Path("ast2python/translator.py").read_text(encoding="utf-8")

    method_start = source.index("    def _collect_globals")
    method_end = source.index("    def _emit_statement", method_start)
    method_source = source[method_start:method_end]

    assert "collect_globals(self, program)" in method_source
    assert "item.kind == \"VarDeclaration\"" not in method_source
    assert "ctx.declare_var" not in method_source


def test_translator_delegates_declaration_metadata_to_helper() -> None:
    source = Path("ast2python/translator.py").read_text(encoding="utf-8")

    method_start = source.index("    def _collect_declaration_metadata")
    method_end = source.index("    def _strategy_context_kwargs", method_start)
    method_source = source[method_start:method_end]

    assert "collect_declaration_metadata(self, declaration, DECLARATION_CONTEXT_FIELDS)" in method_source
    assert "unsupported_declaration_args.append" not in method_source
    assert "ctx.strategy_metadata = metadata" not in method_source


def test_translator_delegates_strategy_context_kwargs_to_helper() -> None:
    source = Path("ast2python/translator.py").read_text(encoding="utf-8")

    method_start = source.index("    def _strategy_context_kwargs")
    method_end = source.index("    def _literal_or_rendered", method_start)
    method_source = source[method_start:method_end]

    assert "strategy_context_kwargs(" in method_source
    assert "STRATEGY_CONTEXT_FIELDS" in method_source
    assert "unsupported_declaration_args.append" not in method_source
    assert "ctx.strategy_metadata = metadata" not in method_source


def test_translator_delegates_request_detection_to_metadata_helper() -> None:
    source = Path("ast2python/translator.py").read_text(encoding="utf-8")

    request_start = source.index("    def _contains_request_call")
    request_end = source.index("    def _contains_any_request_call", request_start)
    any_start = request_end
    any_end = source.index("    def _diagnose_request_security_lower_tf_safety", any_start)

    assert "return contains_request_call(node)" in source[request_start:request_end]
    assert "return contains_any_request_call(node)" in source[any_start:any_end]
    assert "for descendant in" not in source[request_start:request_end]
    assert "chain.startswith(\"request.\")" not in source[any_start:any_end]


def test_translator_delegates_input_helpers_to_input_emitter() -> None:
    source = Path("ast2python/translator.py").read_text(encoding="utf-8")

    runtime_start = source.index("    def _translate_input_runtime_lookup")
    runtime_end = source.index("    def _bind_or_raise", runtime_start)
    is_start = source.index("    def _is_input_call")
    is_end = source.index("    def _build_input_metadata", is_start)
    metadata_start = is_end
    metadata_end = source.index("    def _infer_dtype", metadata_start)

    assert "return self.input_emitter.translate_runtime_lookup(node)" in source[runtime_start:runtime_end]
    assert "return self.input_emitter.is_input_call(node)" in source[is_start:is_end]
    assert (
        "return self.input_emitter.build_metadata(declaration, initializer, py_name)"
        in source[metadata_start:metadata_end]
    )
    assert "input.* requires a default value" not in source
    assert "input declaration is missing a valid callee" not in source


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
