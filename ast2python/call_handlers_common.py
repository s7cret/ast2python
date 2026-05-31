from __future__ import annotations

from ast2python.call_handler_types import CallNode, CallTranslator


def input_runtime(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    return translator._translate_input_runtime_lookup(node)


def na(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    return translator._translate_na_helper_call("na", node, runtime_expr=runtime_expr)


def nz(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    return translator._translate_na_helper_call("nz", node, runtime_expr=runtime_expr)


def fixnan(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    return translator._translate_na_helper_call("fixnan", node, runtime_expr=runtime_expr)


def alert(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    return translator._translate_alert_call("alert", node, runtime_expr=runtime_expr)


def alertcondition(translator: CallTranslator, node: CallNode, runtime_expr: str) -> str:
    return translator._translate_alert_call("alertcondition", node, runtime_expr=runtime_expr)
