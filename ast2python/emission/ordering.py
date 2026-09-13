"""Stable current-bar dependency ordering for admitted Pine v1/v2 global statements."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ast2python.errors import BundleInvariantError

if TYPE_CHECKING:
    from ast2python.emission.context import EmissionContext


def ordered_global_items(ctx: EmissionContext, items: tuple[str, ...]) -> tuple[str, ...]:
    if ctx.plan.pine_version not in {1, 2}:
        return items

    strict = ctx._attrs(ctx.plan.root_ir_id).get("lexical_binding_ids") is True
    declarations: dict[str, str] = {}
    for key in items:
        if ctx._attrs(key).get("ast_kind") == "VarDeclaration":
            name = (
                ctx._attrs(key).get("symbol_id")
                if strict
                else ctx._lookup_local(ctx._scope(key), str(ctx._fields(key).get("name")))
            )
            if name is not None:
                declarations[name] = key

    def dependencies(root: str) -> tuple[str, ...]:
        found: dict[str, None] = {}
        pending = [root]
        visited: set[str] = set()
        while pending:
            key = pending.pop()
            if key in visited:
                continue
            visited.add(key)
            attrs = ctx._attrs(key)
            kind = attrs.get("ast_kind")
            if kind in {"FunctionDeclaration", "MethodDeclaration"}:
                continue
            if kind == "Identifier" and (
                strict or str(attrs.get("symbol_id", "")).startswith("user:variable:")
            ):
                name = (
                    attrs.get("symbol_id")
                    if strict
                    else ctx._lookup_local(ctx._scope(key), str(ctx._fields(key).get("name")))
                )
                dependency = declarations.get(name) if name is not None else None
                if dependency is not None:
                    found[dependency] = None
            children = ctx._node(key).child_ir_ids
            if kind == "HistoryRefExpr":
                offsets = ctx._role(key, "offset")
                if len(offsets) == 1:
                    value = ctx._attrs(offsets[0]).get("const_value")
                    # Positive constant history reads the prior bar, not this initializer.
                    # Zero/dynamic offsets retain the dependency; never assume they are past.
                    if type(value) is int and value > 0:
                        children = offsets
            pending.extend(reversed(children))
        return tuple(found)

    ordered: list[str] = []
    completed: set[str] = set()
    active: set[str] = set()
    for item in items:
        pending_items = [(item, False)]
        while pending_items:
            key, expanded = pending_items.pop()
            if key in completed:
                continue
            if expanded:
                active.remove(key)
                completed.add(key)
                ordered.append(key)
                continue
            if key in active:
                raise BundleInvariantError(
                    "A2P_FORWARD_REFERENCE_CYCLE",
                    "current-bar forward references form a declaration cycle",
                    details={"ir_id": key},
                )
            active.add(key)
            pending_items.append((key, True))
            pending_items.extend((dependency, False) for dependency in reversed(dependencies(key)))
    return tuple(ordered)


def prepare_historical_series(ctx: EmissionContext, items: tuple[str, ...]) -> None:
    """Emit only explicit, owned reservation IR through the declared target primitive."""
    from ast2python.lowering.history_reservation import CAPABILITY, OPERATION

    for key in ctx._role(ctx.plan.root_ir_id, "history_reservations"):
        if (
            ctx._node(key).opcode != OPERATION
            or CAPABILITY not in ctx.plan.required_capabilities
            or OPERATION not in ctx.plan.required_operations
        ):
            raise BundleInvariantError("A2P_HISTORY_RESERVATION_PLAN", "unbound reservation IR")
        ctx._require_language_contract(CAPABILITY)
        declaration = ctx._fields(key).get("declaration_ir_id")
        if declaration not in items or ctx._attrs(declaration).get("ast_kind") != "VarDeclaration":
            raise BundleInvariantError(
                "A2P_HISTORY_RESERVATION_PLAN", "reservation lacks its global declaration"
            )
        name = str(ctx._fields(declaration).get("name"))
        sid = ctx.series_ids.get((ctx._scope(declaration), name))
        dtype = ctx._declaration_type(declaration)
        if sid is None or dtype not in {"bool", "color", "float", "int", "string"}:
            raise BundleInvariantError(
                "A2P_HISTORY_RESERVATION_PLAN", "reservation lacks typed scalar storage"
            )
        call = ctx._runtime_operation(
            OPERATION, repr(sid), repr(dtype), repr(ctx._history_policy(sid))
        )
        ctx.writer.line(call, ir_ids=(key,), origin="LOWERING")
