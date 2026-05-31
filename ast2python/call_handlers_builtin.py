from __future__ import annotations

from typing import Any


def builtin_ta(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_ta_call(callee_chain, node, runtime_expr=runtime_expr)


def builtin_math(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_math_call(callee_chain, node, runtime_expr=runtime_expr)


def builtin_str(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_str_call(callee_chain, node, runtime_expr=runtime_expr)


def builtin_ref(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_reference_call(callee_chain, node, runtime_expr=runtime_expr)
