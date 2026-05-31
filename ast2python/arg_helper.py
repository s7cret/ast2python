"""Call argument extraction helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ast2python.binder import BUILTIN_SIGNATURES

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTNode


def call_arguments(node: "ASTNode") -> list[tuple[str | None, "ASTNode"]]:
    """Extract (name, value) pairs from a Pine call-expression node."""
    result: list[tuple[str | None, "ASTNode"]] = []
    for argument in node.children("arguments", "args"):
        value = argument.child("value") or argument.child("expression")
        if value is None:
            from ast2python.errors import UnsupportedNodeError
            raise UnsupportedNodeError("Argument missing value")
        result.append((argument.field("name"), value))
    return result


def ordered_call_arguments(
    name: str, node: "ASTNode"
) -> list[tuple[str | None, "ASTNode"]]:
    """Reorder call arguments to match BUILTIN_SIGNATURES parameter order."""
    spec = BUILTIN_SIGNATURES[name]
    raw = call_arguments(node)
    if spec.vararg is not None:
        return raw
    ordered: list[tuple[str | None, "ASTNode"] | None] = [None] * len(spec.parameters)
    extras: list[tuple[str | None, "ASTNode"]] = []
    name_to_index = {param.name: index for index, param in enumerate(spec.parameters)}
    seen_named = False
    for index, (arg_name, arg) in enumerate(raw):
        if arg_name is None and not seen_named:
            if index < len(ordered):
                ordered[index] = (None, arg)
            continue
        if arg_name is None:
            extras.append((None, arg))
            continue
        seen_named = True
        if arg_name in name_to_index:
            ordered[name_to_index[arg_name]] = (arg_name, arg)
        else:
            extras.append((arg_name, arg))
    return [item for item in ordered if item is not None] + extras
