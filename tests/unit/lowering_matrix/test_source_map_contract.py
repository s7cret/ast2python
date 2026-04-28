from __future__ import annotations

from pathlib import Path

from ast2python.lowering_matrix import (
    load_source_map_contract,
    source_map_contract_markdown,
    validate_source_map_contract,
)
from ast2python.translator import Translator


def test_bundled_source_map_contract_validates() -> None:
    validate_source_map_contract()


def test_source_map_contract_fields_match_translation_result() -> None:
    fixture = Path("tests/fixtures/pine2ast/current_basic_indicator.ast.json")
    result = Translator().translate_file(fixture, module_name="contract_probe")
    contract_fields = set(load_source_map_contract()["required_fields"])

    assert result.source_map
    assert contract_fields <= set(result.source_map[0])
    assert "source_map_executable_line_ratio" in result.coverage


def test_source_map_contract_markdown_exports_guarantees() -> None:
    text = source_map_contract_markdown()

    assert "# AST2Python Source Map Contract" in text
    assert "`python_line`" in text
    assert "not a full reversible compiler map" in text
