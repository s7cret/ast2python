from __future__ import annotations

from typing import Any

from ast2python.ast.schema import ASTNode


def member_chain(node: ASTNode) -> str | None:
    if node.kind == "Identifier":
        name = node.field("name")
        return name if isinstance(name, str) else None
    if node.kind == "GenericInstantiationExpr":
        base = node.child("base")
        return None if base is None else member_chain(base)
    if node.kind != "MemberAccessExpr":
        return None
    base = node.child("object")
    member = node.field("member")
    if base is None or not isinstance(member, str):
        return None
    prefix = member_chain(base)
    if prefix is None:
        return None
    return f"{prefix}.{member}"


def literal_value(node: ASTNode) -> Any:
    return node.field("value")
