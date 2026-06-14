"""Compatibility wrappers for historical metadata type-inference helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ast2python.translator_mixins.type_inference import infer_type_info

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTNode


def infer_dtype(translator: Any, node: ASTNode | None) -> str:
    return infer_type_info(translator, node).base_type


def _type_ref_name(node: ASTNode) -> str | None:
    type_ref = node.child("type_ref")
    if type_ref is None:
        return None
    name = type_ref.field("name")
    return str(name) if isinstance(name, str) else None
