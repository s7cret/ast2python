"""Switch/case AST node helpers for Pine v6 → Python translation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTNode


def switch_cases(node: ASTNode) -> list[ASTNode]:
    """Return the case/branch nodes from a Pine switch/switch-expression node."""
    return node.children("cases", "branches", "arms")


def case_condition(case: ASTNode) -> ASTNode | None:
    """Return the condition/test/match/value child of a case node."""
    return (
        case.child("condition") or case.child("match") or case.child("value") or case.child("test")
    )


def case_body(case: ASTNode) -> ASTNode | None:
    """Return the body/block/then child of a case node."""
    return case.child("body") or case.child("block") or case.child("then")
