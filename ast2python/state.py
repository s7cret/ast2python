from __future__ import annotations

import hashlib

from ast2python.ast.schema import ASTNode
from ast2python.context import TranslationContext
from ast2python.diagnostics import MISSING_LOC_STATE_ID_HASH, Severity


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def state_id_for_call(ctx: TranslationContext, node: ASTNode, func_name: str) -> str:
    normalized = func_name.split(".")[-1]
    loc = node.loc
    if loc is not None and loc.line is not None and loc.column is not None:
        key = (loc.line, loc.column, normalized)
        ordinal = ctx.state_id_counts.get(key, 0) + 1
        ctx.state_id_counts[key] = ordinal
        return f"L{loc.line}_C{loc.column}_{normalized}_{ordinal}"
    fallback = stable_hash(f"{normalized}|{node.kind}|{node.source or ''}|{node.raw!r}")[:16]
    ctx.add_diagnostic(
        MISSING_LOC_STATE_ID_HASH,
        "state_id generated from AST hash because source location is missing",
        Severity.WARNING,
        location=loc,
        details={"function": normalized},
    )
    return f"N{fallback}"


def state_id_py_expr(ctx: TranslationContext, base_id: str) -> str:
    """Return a Python expression string for the state_id kwarg.

    When inside a user-defined function, prefixes the state_id with the
    runtime call-site variable ``_cs_id`` so that each call site gets
    its own isolated stateful series (ta.ema, ta.lowest, etc.).
    Without this, calling a UDF twice per bar (e.g. for strategy logic
    + plot) shares the same internal EMA state and corrupts the indicator.
    """
    if ctx.current_function is not None:
        return f'_cs_id + "{base_id}"'
    return f'"{base_id}"'
