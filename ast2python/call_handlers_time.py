from __future__ import annotations

from ast2python.call_handler_types import CallNode, CallTranslator, ExactCallHandler


def timestamp(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    return translator.time_emitter.translate_timestamp_call(node)


def make_date_helper(name: str) -> ExactCallHandler:
    def handler(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
        return translator.time_emitter.translate_date_helper_call(
            name,
            node,
            runtime_expr=runtime_expr,
        )

    return handler


def builtin_time_exact(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    return translator.time_emitter.translate_time_call("time", node, runtime_expr=runtime_expr)


def builtin_time_close_exact(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    return translator.time_emitter.translate_time_call(
        "time_close",
        node,
        runtime_expr=runtime_expr,
    )


def timeframe_change_exact(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    arguments = translator._call_arguments(node)
    rendered = [
        translator.translate_expression(arg, runtime_expr=runtime_expr) for _, arg in arguments
    ]
    translator.ctx.coverage.builtin("timeframe.change")
    return f"{runtime_expr}.timefunc.change({', '.join(rendered)}, runtime={runtime_expr})"
