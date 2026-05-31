from __future__ import annotations

from typing import Any


def builtin_strategy_prefix(
    translator: Any, callee_chain: str, node: Any, runtime_expr: str
) -> Any:
    return translator._translate_strategy_call(callee_chain, node, runtime_expr=runtime_expr)


def strategy_long(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_strategy_call("strategy.long", node, runtime_expr=runtime_expr)


def strategy_short(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_strategy_call("strategy.short", node, runtime_expr=runtime_expr)
