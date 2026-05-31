from __future__ import annotations

from ast2python.call_handler_types import CallNode, CallTranslator


def builtin_ta(
    translator: CallTranslator, callee_chain: str, node: CallNode, runtime_expr: str
) -> str:
    return translator._translate_ta_call(callee_chain, node, runtime_expr=runtime_expr)


def builtin_math(
    translator: CallTranslator, callee_chain: str, node: CallNode, runtime_expr: str
) -> str:
    return translator._translate_math_call(callee_chain, node, runtime_expr=runtime_expr)


def builtin_str(
    translator: CallTranslator, callee_chain: str, node: CallNode, runtime_expr: str
) -> str:
    return translator._translate_str_call(callee_chain, node, runtime_expr=runtime_expr)


def builtin_ref(
    translator: CallTranslator, callee_chain: str, node: CallNode, runtime_expr: str
) -> str:
    return translator._translate_reference_call(callee_chain, node, runtime_expr=runtime_expr)
