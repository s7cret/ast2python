from __future__ import annotations

import pytest

from ast2python.lowering_matrix import (
    LoweringMatrixError,
    load_lowering_entries,
    load_lowering_matrix,
    lowering_matrix_markdown,
    validate_lowering_matrix,
    validate_lowering_matrix_payload,
)


def test_bundled_lowering_matrix_validates() -> None:
    validate_lowering_matrix()


def test_lowering_matrix_rejects_duplicate_kinds() -> None:
    payload = load_lowering_matrix()
    first = dict(payload["entries"][0])
    payload["entries"] = [first, dict(first)]

    with pytest.raises(LoweringMatrixError, match="duplicate lowering matrix"):
        validate_lowering_matrix_payload(payload)


def test_lowering_matrix_covers_p0_runtime_contract_nodes() -> None:
    entries = {entry.ast_kind: entry for entry in load_lowering_entries()}

    for kind in [
        "Program",
        "VarDeclaration",
        "ExpressionStatement",
        "CallExpr",
        "HistoryRefExpr",
        "IfStructure",
        "ForRangeStructure",
        "request.security",
        "strategy.*",
    ]:
        assert kind in entries
        assert entries[kind].priority == "P0"
        assert entries[kind].runtime_contract == "1.4"


def test_lowering_matrix_markdown_exports_status_table() -> None:
    text = lowering_matrix_markdown()

    assert "# AST2Python Lowering Matrix" in text
    assert "`CallExpr`" in text
    assert "`request.security`" in text
    assert "full TradingView compatibility" in text
