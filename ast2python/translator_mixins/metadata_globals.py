"""Global declaration collection for the translator frontend."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ast2python.translator_constants import (
    ENUM_DECLARATIONS,
    FUNCTION_DECLARATIONS,
    METHOD_DECLARATIONS,
    UDT_DECLARATIONS,
)
from ast2python.translator_support import member_chain
from ast2python.types import make_type_info

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTProgram


REFERENCE_TYPE_NAMES = {"line", "label", "box", "table", "PineObjectId"}


def _record_declared_type_metadata(translator: Any, info: Any, initializer: Any | None) -> None:
    if initializer is not None:
        info.type_info = translator._infer_type_info(initializer)
    elif info.type_ref in REFERENCE_TYPE_NAMES:
        info.type_info = make_type_info("PineObjectId", info.qualifier, is_series=info.is_series)
    if info.type_info is not None:
        translator.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = info.type_info.to_dict()


def _collect_tuple_declaration(translator: Any, item: Any) -> None:
    initializer = item.child("initializer") or item.child("value")
    for name in translator._tuple_targets(item):
        if name == "_":
            continue
        info = translator.ctx.declare_var(
            name,
            type_ref=None,
            qualifier=item.field("explicit_qualifier"),
            declaration_kind=str(item.field("mode") or "normal"),
            is_series=True,
            is_mutable=True,
            loc=item.loc,
        )
        _record_declared_type_metadata(translator, info, initializer)
        translator.global_series.append((info, translator._infer_dtype(initializer)))


def _collect_input_declaration(translator: Any, item: Any, initializer: Any) -> None:
    info = translator.ctx.declare_var(
        item.field("name"),
        type_ref=translator._type_ref_name(item),
        qualifier="input",
        declaration_kind="input",
        is_series=True,
        is_mutable=False,
        loc=item.loc,
    )
    meta = translator._build_input_metadata(item, initializer, info.py_name)
    info.type_info = make_type_info(
        meta["type"],
        "input",
        is_series=True,
        can_be_na=meta["type"] != "bool",
    )
    translator.ctx.type_metadata[f"global:{info.pine_name}"] = info.type_info.to_dict()
    translator.input_series.append((info, meta["type"], meta))
    translator.ctx.input_metadata.append(meta["public"])
    callee = initializer.child("callee")
    chain = None if callee is None else member_chain(callee)
    if chain is not None:
        translator.ctx.coverage.builtin(chain)


def _collect_var_declaration(translator: Any, item: Any) -> None:
    initializer = item.child("initializer")
    if initializer is not None and translator._is_input_call(initializer):
        _collect_input_declaration(translator, item, initializer)
        return
    info = translator.ctx.declare_var(
        item.field("name"),
        type_ref=translator._type_ref_name(item),
        qualifier=item.field("explicit_qualifier"),
        declaration_kind=str(item.field("mode") or "normal"),
        is_series=True,
        is_mutable=True,
        loc=item.loc,
    )
    _record_declared_type_metadata(translator, info, initializer)
    translator.global_series.append((info, translator._infer_dtype(initializer)))


def _record_nested_builtin_coverage(translator: Any, item: Any) -> None:
    for member in item.descendants():
        if member.kind != "CallExpr":
            continue
        callee = member.child("callee")
        chain = None if callee is None else member_chain(callee)
        if chain is not None:
            translator.ctx.coverage.builtin(chain)


def collect_globals(translator: Any, program: ASTProgram) -> None:
    """Collect global variables, inputs and top-level callable declarations."""
    for item in program.items:
        if item.kind == "ImportDeclaration":
            translator._record_import_alias(item)
            continue
        if item.kind in FUNCTION_DECLARATIONS:
            name = item.field("name")
            if name is not None:
                translator.functions.add(str(name))
            continue
        if item.kind in METHOD_DECLARATIONS:
            name = item.field("name")
            if name is not None:
                translator.methods.add(str(name))
            continue
        if item.kind in UDT_DECLARATIONS | ENUM_DECLARATIONS | {"AlertCondition"}:
            continue
        if item.kind == "TupleDeclaration":
            _collect_tuple_declaration(translator, item)
            continue
        if item.kind == "VarDeclaration":
            _collect_var_declaration(translator, item)
            continue
        _record_nested_builtin_coverage(translator, item)
