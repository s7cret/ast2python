from __future__ import annotations

from collections.abc import Callable
from typing import Any

ExactCallHandler = Callable[[Any, Any, str], Any]
PrefixCallHandler = Callable[[Any, str, Any, str], Any]


def request_security(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_request_security(node, runtime_expr=runtime_expr)


def request_security_lower_tf(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_request_security_lower_tf(node, runtime_expr=runtime_expr)


def timestamp(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator.time_emitter.translate_timestamp_call(node)


def make_date_helper(name: str) -> ExactCallHandler:
    def handler(translator: Any, node: Any, runtime_expr: str) -> Any:
        return translator.time_emitter.translate_date_helper_call(
            name,
            node,
            runtime_expr=runtime_expr,
        )

    return handler


def unsupported_request(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_unsupported_request_call(
        callee_chain,
        node,
        runtime_expr=runtime_expr,
    )


def input_runtime(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_input_runtime_lookup(node)


def builtin_ta(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_ta_call(callee_chain, node, runtime_expr=runtime_expr)


def builtin_math(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_math_call(callee_chain, node, runtime_expr=runtime_expr)


def builtin_str(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_str_call(callee_chain, node, runtime_expr=runtime_expr)


def builtin_ref(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_reference_call(callee_chain, node, runtime_expr=runtime_expr)


def builtin_strategy_prefix(
    translator: Any, callee_chain: str, node: Any, runtime_expr: str
) -> Any:
    return translator._translate_strategy_call(callee_chain, node, runtime_expr=runtime_expr)


def builtin_time_exact(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator.time_emitter.translate_time_call("time", node, runtime_expr=runtime_expr)


def builtin_time_close_exact(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator.time_emitter.translate_time_call(
        "time_close",
        node,
        runtime_expr=runtime_expr,
    )


def timeframe_change_exact(translator: Any, node: Any, runtime_expr: str) -> str:
    arguments = translator._call_arguments(node)
    rendered = [
        translator.translate_expression(arg, runtime_expr=runtime_expr) for _, arg in arguments
    ]
    translator.ctx.coverage.builtin("timeframe.change")
    return f"{runtime_expr}.timefunc.change({', '.join(rendered)}, runtime={runtime_expr})"


def na(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_na_helper_call("na", node, runtime_expr=runtime_expr)


def nz(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_na_helper_call("nz", node, runtime_expr=runtime_expr)


def fixnan(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_na_helper_call("fixnan", node, runtime_expr=runtime_expr)


def alert(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_alert_call("alert", node, runtime_expr=runtime_expr)


def alertcondition(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_alert_call("alertcondition", node, runtime_expr=runtime_expr)


def strategy_long(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_strategy_call("strategy.long", node, runtime_expr=runtime_expr)


def strategy_short(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_strategy_call("strategy.short", node, runtime_expr=runtime_expr)
