"""Resolve identifier occurrences by producer identities, never by spelling overrides."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pine2ast.catalog import CatalogRepository

from ast2python.errors import BundleInvariantError

if TYPE_CHECKING:
    from ast2python.emission.context import EmissionContext


def prepare_lexical_names(ctx: EmissionContext) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for key in ctx.plan.ordered_ir_ids:
        attrs, fields = ctx._attrs(key), ctx._fields(key)
        kind, name = attrs.get("ast_kind"), fields.get("name")
        source = ctx._node(key).source.node_id
        if kind in {"VarDeclaration", "Parameter", "TupleTarget"} and isinstance(name, str):
            symbol = f"user:{kind.lower()}:{name}:{source}"
            if attrs.get("symbol_id") != symbol:
                raise BundleInvariantError(
                    "A2P_LEXICAL_BINDING_IDENTITY", "declaration identity differs from its owner"
                )
            result[symbol] = (name, ctx.names_by_source[source])
        elif kind in {"ForRangeStructure", "ForInStructure"}:
            names = (
                [fields.get("variable")]
                if kind == "ForRangeStructure"
                else ctx._fields(ctx._role(key, "target")[0]).get("names", [])
            )
            role = "iterator" if kind == "ForRangeStructure" else "target"
            for variable in names:
                if not isinstance(variable, str) or variable == "_":
                    continue
                pyname = ctx._lookup_local(
                    "scope:loop:" + source if ctx.exact_pinelib else ctx._scope(key), variable
                )
                if pyname is None:
                    raise BundleInvariantError(
                        "A2P_LEXICAL_BINDING_IDENTITY", "implicit loop binder lacks storage"
                    )
                result[f"user:{kind.lower()}:{variable}:{source}:role:{role}"] = (variable, pyname)
        elif kind == "MethodDeclaration" and key in ctx.method_receivers:
            receiver = fields["receiver_name"]
            result[f"user:methodreceiver:{receiver}:{source}:role:receiver"] = (
                receiver,
                ctx.method_receivers[key][0],
            )
    return result


def catalog_entry(ctx: EmissionContext, name: str) -> Mapping[str, Any] | None:
    catalog = CatalogRepository.default().readonly_view(ctx.plan.pine_version)
    if catalog["catalog_hash"] != ctx.plan.catalog_hash:
        raise BundleInvariantError(
            "A2P_CATALOG_OCCURRENCE", "catalog differs from the admitted version identity"
        )
    for section in ("variables", "constants", "types", "namespaces", "functions"):
        row = catalog.get(section, {}).get(name)
        if isinstance(row, Mapping) and row.get("symbol_id"):
            return row
    return None


def written_name(ctx: EmissionContext, key: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    while key not in seen:
        seen.add(key)
        attrs, fields = ctx._attrs(key), ctx._fields(key)
        if attrs.get("ast_kind") == "Identifier":
            parts.append(str(fields.get("name") or ""))
            return ".".join(reversed(parts))
        objects = ctx._role(key, "object")
        if attrs.get("ast_kind") != "MemberAccessExpr" or len(objects) != 1:
            break
        parts.append(str(fields.get("member") or ""))
        key = objects[0]
    raise BundleInvariantError(
        "A2P_CATALOG_OCCURRENCE", "catalog occurrence has no admitted static name"
    )


def validate_catalog_occurrence(ctx: EmissionContext, key: str) -> None:
    row = catalog_entry(ctx, written_name(ctx, key))
    if row is None or ctx._attrs(key).get("symbol_id") != row.get("symbol_id"):
        raise BundleInvariantError(
            "A2P_CATALOG_OCCURRENCE", "symbol identity does not match its catalog occurrence"
        )


def identifier_local(ctx: EmissionContext, key: str) -> str | None:
    attrs, fields = ctx._attrs(key), ctx._fields(key)
    strict = ctx._attrs(ctx.plan.root_ir_id).get("lexical_binding_ids") is True
    if not strict:
        if ctx.exact_pinelib:
            raise BundleInvariantError(
                "A2P_LEXICAL_CONTRACT", "exact execution requires producer lexical identities"
            )
        return ctx._lookup_local(ctx._scope(key), str(fields.get("name") or ""))
    symbol = attrs.get("symbol_id")
    if not isinstance(symbol, str):
        raise BundleInvariantError(
            "A2P_LEXICAL_BINDING_IDENTITY", "identifier lacks producer identity"
        )
    bound = ctx.lexical_names.get(symbol)
    if bound is not None:
        if fields.get("name") != bound[0]:
            raise BundleInvariantError(
                "A2P_LEXICAL_BINDING_IDENTITY", "identifier name differs from resolved declaration"
            )
        declaration = ctx.declarations_by_py.get(bound[1])
        if ctx.exact_pinelib:
            owner_scopes = (
                {declaration[0]}
                if declaration is not None
                else {scope for (scope, _), pyname in ctx.local_names.items() if pyname == bound[1]}
            )
            if len(owner_scopes) != 1:
                raise BundleInvariantError(
                    "A2P_LEXICAL_BINDING_SCOPE", "binder lacks a unique owner scope"
                )
            owner_scope = next(iter(owner_scopes))
            scope: str | None = ctx._scope(key)
            visited: set[str] = set()
            while scope is not None and scope != owner_scope:
                if scope in visited:
                    raise BundleInvariantError(
                        "A2P_LEXICAL_BINDING_SCOPE", "cyclic lexical ancestry"
                    )
                visited.add(scope)
                scope = ctx.scope_parents.get(scope)
            if scope is None:
                raise BundleInvariantError(
                    "A2P_LEXICAL_BINDING_SCOPE",
                    "resolved declaration is outside the occurrence scope",
                )
        if ctx.exact_pinelib and ctx.plan.pine_version in {1, 2} and declaration is not None:
            owner = ctx._node(declaration[1])
            if (
                declaration[0] == "scope:global"
                and ctx._attrs(declaration[1]).get("ast_kind") == "VarDeclaration"
                and ctx._node(key).source.span["start_offset"] < owner.source.span["start_offset"]
                and catalog_entry(ctx, bound[0]) is not None
            ):
                raise BundleInvariantError(
                    "A2P_HISTORICAL_BINDING_AMBIGUOUS",
                    "builtin-before-shadow needs a documented historical resolution rule",
                )
        return bound[1]
    if symbol.startswith("user:") and not symbol.startswith(
        ("user:function:", "user:method:", "user:type:")
    ):
        raise BundleInvariantError(
            "A2P_LEXICAL_BINDING_IDENTITY", "producer declaration identity is not bound"
        )
    if not symbol.startswith("user:"):
        validate_catalog_occurrence(ctx, key)
    return None
