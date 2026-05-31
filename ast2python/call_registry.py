from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ast2python.emitters.inputs import INPUT_CALLS
from ast2python.emitters.time import DATE_HELPERS

ExactCallHandler = Callable[[Any, Any, str], Any]
PrefixCallHandler = Callable[[Any, str, Any, str], Any]


def _h_request_security(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_request_security(node, runtime_expr=runtime_expr)


def _h_request_security_lower_tf(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_request_security_lower_tf(node, runtime_expr=runtime_expr)


def _h_timestamp(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator.time_emitter.translate_timestamp_call(node)


def _make_date_helper(name: str) -> ExactCallHandler:
    def handler(translator: Any, node: Any, runtime_expr: str) -> Any:
        return translator.time_emitter.translate_date_helper_call(
            name,
            node,
            runtime_expr=runtime_expr,
        )

    return handler


def _h_unsupported_request(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_unsupported_request_call(
        callee_chain,
        node,
        runtime_expr=runtime_expr,
    )


def _h_input_runtime(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_input_runtime_lookup(node)


def _h_builtin_ta(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_ta_call(callee_chain, node, runtime_expr=runtime_expr)


def _h_builtin_math(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_math_call(callee_chain, node, runtime_expr=runtime_expr)


def _h_builtin_str(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_str_call(callee_chain, node, runtime_expr=runtime_expr)


def _h_builtin_ref(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_reference_call(callee_chain, node, runtime_expr=runtime_expr)


def _h_builtin_strategy_prefix(
    translator: Any, callee_chain: str, node: Any, runtime_expr: str
) -> Any:
    return translator._translate_strategy_call(callee_chain, node, runtime_expr=runtime_expr)


def _h_builtin_time_exact(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator.time_emitter.translate_time_call("time", node, runtime_expr=runtime_expr)


def _h_builtin_time_close_exact(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator.time_emitter.translate_time_call(
        "time_close",
        node,
        runtime_expr=runtime_expr,
    )


def _h_timeframe_change_exact(translator: Any, node: Any, runtime_expr: str) -> str:
    arguments = translator._call_arguments(node)
    rendered = [
        translator.translate_expression(arg, runtime_expr=runtime_expr) for _, arg in arguments
    ]
    translator.ctx.coverage.builtin("timeframe.change")
    return f"{runtime_expr}.timefunc.change({', '.join(rendered)}, runtime={runtime_expr})"


def _h_na(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_na_helper_call("na", node, runtime_expr=runtime_expr)


def _h_nz(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_na_helper_call("nz", node, runtime_expr=runtime_expr)


def _h_fixnan(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_na_helper_call("fixnan", node, runtime_expr=runtime_expr)


def _h_alert(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_alert_call("alert", node, runtime_expr=runtime_expr)


def _h_alertcondition(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_alert_call("alertcondition", node, runtime_expr=runtime_expr)


def _h_strategy_long(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_strategy_call("strategy.long", node, runtime_expr=runtime_expr)


def _h_strategy_short(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_strategy_call("strategy.short", node, runtime_expr=runtime_expr)


CALL_EXACT: dict[str, ExactCallHandler] = {
    "request.security": _h_request_security,
    "request.security_lower_tf": _h_request_security_lower_tf,
    "timestamp": _h_timestamp,
    "time": _h_builtin_time_exact,
    "time_close": _h_builtin_time_close_exact,
    "timeframe.change": _h_timeframe_change_exact,
    "na": _h_na,
    "nz": _h_nz,
    "fixnan": _h_fixnan,
    "alert": _h_alert,
    "alertcondition": _h_alertcondition,
    "strategy.long": _h_strategy_long,
    "strategy.short": _h_strategy_short,
}

for _input_call in INPUT_CALLS:
    CALL_EXACT[_input_call] = _h_input_runtime

for _date_helper in DATE_HELPERS:
    CALL_EXACT[_date_helper] = _make_date_helper(_date_helper)

CALL_PREFIX: list[tuple[str, PrefixCallHandler]] = [
    ("request.", _h_unsupported_request),
    ("ta.", _h_builtin_ta),
    ("math.", _h_builtin_math),
    ("str.", _h_builtin_str),
    ("array.", _h_builtin_ref),
    ("map.", _h_builtin_ref),
    ("matrix.", _h_builtin_ref),
    ("strategy.", _h_builtin_strategy_prefix),
]
