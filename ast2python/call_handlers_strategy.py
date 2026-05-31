from __future__ import annotations

from ast2python.call_handler_types import CallNode, CallTranslator


def builtin_strategy_prefix(
    translator: CallTranslator, callee_chain: str, node: CallNode, runtime_expr: str
) -> str:
    return translator._translate_strategy_call(callee_chain, node, runtime_expr=runtime_expr)


def strategy_long(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    return translator._translate_strategy_call("strategy.long", node, runtime_expr=runtime_expr)


def strategy_short(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    return translator._translate_strategy_call("strategy.short", node, runtime_expr=runtime_expr)
