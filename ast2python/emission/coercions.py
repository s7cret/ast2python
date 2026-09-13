"""Render only producer-declared operand coercions; leave numeric ABI guards strict."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ast2python.emission.context import EmissionContext


def binary_operand(ctx: EmissionContext, parent: str, child: str) -> str:
    expression = ctx._expr(child)
    dtype = ctx._node(child).result_type
    if not ctx.exact_pinelib or ctx.plan.pine_version not in {1, 2}:
        return expression
    if dtype is None or dtype.base != "bool":
        return expression
    admitted = {
        "source_type": "bool",
        "target_type": "int",
        "reason": f"coercion.bool_to_number.allow.v{ctx.plan.pine_version}",
    }
    if admitted not in ctx._attrs(parent).get("coercions", []):
        return expression
    # Evaluate once; preserve canonical NA and let the target reject any invalid value.
    return (
        "(lambda _coerced: int(_coerced) if type(_coerced) is bool else _coerced)" f"({expression})"
    )
