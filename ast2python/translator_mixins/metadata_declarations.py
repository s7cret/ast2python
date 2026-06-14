"""Declaration metadata helpers for indicator/strategy/library headers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ast2python.diagnostics import UNSUPPORTED_DECLARATION_ARG, Severity
from ast2python.errors import UnsupportedBuiltinError
from ast2python.translator_support import literal_value

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTNode


def call_arguments(node: ASTNode) -> list[tuple[str | None, ASTNode]]:
    """Extract argument name/value pairs from a CallExpr node."""
    if node.kind != "CallExpr":
        return []
    args: list[tuple[str | None, ASTNode]] = []
    for child in node.children("arguments", "args"):
        if child.kind == "Argument":
            name = child.field("name")
            value = child.child("value") or child.child("expression")
            if value is not None:
                args.append((str(name) if isinstance(name, str) else None, value))
        elif child.kind == "Identifier":
            args.append((None, child))
    return args


def extract_declaration_title(translator: Any, declaration: ASTNode) -> str:
    call = declaration.child("call")
    if call is None:
        return "Generated"
    arguments = translator._call_arguments(call)
    if arguments and arguments[0][0] is None and arguments[0][1].kind == "Literal":
        return str(literal_value(arguments[0][1]))
    return "Generated"


def literal_or_rendered(node: ASTNode, rendered: str) -> Any:
    import ast as pyast

    if node.kind == "Literal":
        return literal_value(node)
    if node.kind == "MemberAccessExpr":
        try:
            return pyast.literal_eval(rendered)
        except (ValueError, SyntaxError):
            return rendered
    return rendered


def _metadata_key(name: str | None, metadata: dict[str, Any]) -> str:
    return name or ("title" if not metadata else f"arg_{len(metadata)}")


def collect_declaration_metadata(
    translator: Any,
    declaration: ASTNode,
    declaration_context_fields: dict[str, set[str]],
) -> None:
    call = declaration.child("call")
    if call is None:
        return
    allowed = declaration_context_fields.get(translator.ctx.mode, set())
    metadata: dict[str, Any] = {}
    for name, value_node in translator._call_arguments(call):
        rendered = translator.translate_expression(value_node)
        metadata[_metadata_key(name, metadata)] = literal_or_rendered(value_node, rendered)
        if name is not None and name not in allowed:
            translator.ctx.add_diagnostic(
                UNSUPPORTED_DECLARATION_ARG,
                f"declaration argument {name!r} is not mapped for {translator.ctx.mode}",
                Severity.ERROR if translator.strict else Severity.WARNING,
                location=value_node.loc,
            )
            translator.ctx.unsupported_declaration_args.append(name)
            if translator.strict:
                raise UnsupportedBuiltinError(name)
    translator.ctx.strategy_metadata = metadata


def strategy_context_kwargs(
    translator: Any,
    declaration: ASTNode,
    strategy_context_fields: set[str],
    declaration_context_fields: dict[str, set[str]],
) -> list[tuple[str, str]]:
    call = declaration.child("call")
    if call is None:
        return []
    kwargs: list[tuple[str, str]] = []
    metadata: dict[str, Any] = {}
    for name, value_node in translator._call_arguments(call):
        rendered = translator.translate_expression(value_node)
        metadata[_metadata_key(name, metadata)] = literal_or_rendered(value_node, rendered)
        if name in strategy_context_fields:
            kwargs.append((name, rendered))
        elif name is not None and name not in declaration_context_fields.get("strategy", set()):
            translator.ctx.add_diagnostic(
                UNSUPPORTED_DECLARATION_ARG,
                f"declaration argument {name!r} is not mapped to StrategyContext",
                Severity.ERROR if translator.strict else Severity.WARNING,
                location=value_node.loc,
            )
            translator.ctx.unsupported_declaration_args.append(name)
            if translator.strict:
                raise UnsupportedBuiltinError(name)
    translator.ctx.strategy_metadata = metadata
    return kwargs
