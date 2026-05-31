from __future__ import annotations

from typing import Any

from ast2python.call_handler_types import ExactCallHandler


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
