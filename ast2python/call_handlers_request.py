from __future__ import annotations

from typing import Any


def request_security(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_request_security(node, runtime_expr=runtime_expr)


def request_security_lower_tf(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_request_security_lower_tf(node, runtime_expr=runtime_expr)


def unsupported_request(translator: Any, callee_chain: str, node: Any, runtime_expr: str) -> Any:
    return translator._translate_unsupported_request_call(
        callee_chain,
        node,
        runtime_expr=runtime_expr,
    )
