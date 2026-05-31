from __future__ import annotations

from collections.abc import Mapping, Sequence

from ast2python.call_handler_types import (
    CalleeNode,
    CallNode,
    CallTranslator,
    ExactCallHandler,
    PrefixCallHandler,
)
from ast2python.diagnostics import UNKNOWN_OVERLOAD, Severity
from ast2python.errors import UnsupportedBuiltinError
from ast2python.naming import snake_case
from ast2python.translator_constants import (
    VISUAL_OBJECT_PRODUCERS,
    VISUAL_STATEMENT_CALLS,
)


def dispatch_call(
    translator: CallTranslator,
    callee_chain: str,
    node: CallNode,
    callee: CalleeNode,
    *,
    runtime_expr: str,
    exact_handlers: Mapping[str, ExactCallHandler],
    prefix_handlers: Sequence[tuple[str, PrefixCallHandler]],
) -> str:
    exact = exact_handlers.get(callee_chain)
    if exact is not None:
        return exact(translator, node, runtime_expr=runtime_expr)

    for prefix, handler in prefix_handlers:
        if callee_chain.startswith(prefix):
            return handler(translator, callee_chain, node, runtime_expr=runtime_expr)

    return dispatch_fallback_call(
        translator,
        callee_chain,
        node,
        callee,
        runtime_expr=runtime_expr,
    )


def dispatch_fallback_call(
    translator: CallTranslator,
    callee_chain: str,
    node: CallNode,
    callee: CalleeNode,
    *,
    runtime_expr: str,
) -> str:
    alias = callee_chain.split(".", 1)[0]
    if alias in translator.ctx.import_aliases and "." in callee_chain:
        return translator._translate_external_library_call(
            callee_chain,
            node,
            runtime_expr=runtime_expr,
        )

    if callee.kind == "MemberAccessExpr":
        obj = callee.child("object")
        member = callee.field("member")
        if obj is not None and isinstance(member, str) and member in translator.methods:
            pieces = [translator.translate_expression(obj, runtime_expr=runtime_expr)]
            pieces.extend(
                translator.translate_expression(arg, runtime_expr=runtime_expr)
                for _, arg in translator._call_arguments(node)
            )
            return f"self.{snake_case(member)}({', '.join(pieces)})"

    if (
        callee_chain in VISUAL_STATEMENT_CALLS
        or callee_chain in VISUAL_OBJECT_PRODUCERS
        or translator._is_visual_method_call(callee_chain)
    ):
        return translator._translate_visual_call(callee_chain, node, runtime_expr=runtime_expr)

    if callee_chain in translator.functions:
        pieces = [
            translator._translate_user_func_arg(arg, runtime_expr=runtime_expr)
            for _, arg in translator._call_arguments(node)
        ]
        return f"self.{snake_case(callee_chain)}({', '.join(pieces)})"

    if callee_chain in translator.methods:
        pieces = [
            translator._translate_user_func_arg(arg, runtime_expr=runtime_expr)
            for _, arg in translator._call_arguments(node)
        ]
        return f"self.{snake_case(callee_chain)}({', '.join(pieces)})"

    if callee_chain and callee_chain[:1].isupper():
        pieces = []
        for arg_name, arg in translator._call_arguments(node):
            rendered = translator.translate_expression(arg, runtime_expr=runtime_expr)
            pieces.append(rendered if arg_name is None else f"{arg_name}={rendered}")
        return f"{callee_chain}({', '.join(pieces)})"

    if callee_chain in {"int", "float", "bool", "str"}:
        helper = {
            "int": "pine_int",
            "float": "pine_float",
            "bool": "pine_bool",
            "str": "pine_str",
        }[callee_chain]
        translator.ctx.imports.require_from("pinelib.core", helper)
        pieces = [
            translator.translate_expression(arg, runtime_expr=runtime_expr)
            for _, arg in translator._call_arguments(node)
        ]
        return f"{helper}({', '.join(pieces)})"

    translator.ctx.add_diagnostic(
        UNKNOWN_OVERLOAD,
        f"unknown or unsupported call overload: {callee_chain}",
        Severity.ERROR if translator.strict else Severity.WARNING,
        location=node.loc,
    )
    raise UnsupportedBuiltinError(callee_chain)
