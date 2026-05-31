from __future__ import annotations

from ast2python.call_handler_types import CallNode, CallTranslator


def request_security(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    return translator._translate_request_security(node, runtime_expr=runtime_expr)


def request_security_lower_tf(
    translator: CallTranslator, node: CallNode, runtime_expr: str
) -> str:
    return translator._translate_request_security_lower_tf(node, runtime_expr=runtime_expr)


def unsupported_request(
    translator: CallTranslator, callee_chain: str, node: CallNode, runtime_expr: str
) -> str:
    return translator._translate_unsupported_request_call(
        callee_chain,
        node,
        runtime_expr=runtime_expr,
    )
