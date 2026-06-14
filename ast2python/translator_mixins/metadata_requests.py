"""Request-call discovery helpers used by metadata and fail-closed checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ast2python.diagnostics import (
    REQUEST_SECURITY_CAPTURE_UNSAFE,
    WARNING_NESTED_SECURITY,
    Severity,
)
from ast2python.errors import ScopeResolutionError
from ast2python.translator_support import member_chain

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTNode


def _call_chain(node: ASTNode) -> str | None:
    if node.kind != "CallExpr":
        return None
    callee = node.child("callee")
    return None if callee is None else member_chain(callee)


def contains_request_call(node: ASTNode) -> bool:
    """Return true if an expression tree contains request.security."""
    return any(_call_chain(item) == "request.security" for item in (node, *node.descendants()))


def contains_any_request_call(node: ASTNode) -> bool:
    """Return true if an expression tree contains any request.* call."""
    return any(
        isinstance(chain, str) and chain.startswith("request.")
        for chain in (_call_chain(item) for item in (node, *node.descendants()))
    )


def is_lower_tf_safe_immutable_scalar_capture(info: Any) -> bool:
    if info.declaration_kind == "input":
        return True
    if info.type_info is not None and info.type_info.qualifier in ("const", "input"):
        return True
    return False


def diagnose_request_security_lower_tf_safety(translator: Any, expression: ASTNode) -> None:
    if expression.kind == "Identifier":
        name = expression.field("name")
        try:
            info = translator.ctx.resolve_var(name)
        except ScopeResolutionError:
            return
        if info is not None and info.is_series and info.declaration_kind != "input":
            if not is_lower_tf_safe_immutable_scalar_capture(info):
                translator.ctx.add_diagnostic(
                    REQUEST_SECURITY_CAPTURE_UNSAFE,
                    f"request.security_lower_tf captures mutable series {name!r}",
                    Severity.ERROR,
                    details={
                        "variable": name,
                        "kind": info.declaration_kind,
                        "capture_type": "mutable_series",
                    },
                )
    for child_node in expression.descendants():
        if child_node is not expression:
            diagnose_request_security_lower_tf_safety(translator, child_node)


def diagnose_request_security_captures(translator: Any, expression: ASTNode) -> None:
    # Compatibility helper for external users. The active translator mixin performs
    # stricter request capture validation, but this keeps the historical helper
    # available without falsely treating the root request.security call as nested.
    nested = any(
        isinstance(chain, str) and chain.startswith("request.")
        for descendant in expression.descendants()
        for chain in [_call_chain(descendant)]
    )
    if nested:
        translator.ctx.add_diagnostic(
            WARNING_NESTED_SECURITY,
            "Nested request.security call detected",
            Severity.WARNING,
            details={"expression": str(expression)},
        )
