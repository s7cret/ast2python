from __future__ import annotations

from typing import Any


def input_runtime(translator: Any, node: Any, runtime_expr: str) -> Any:
    return translator._translate_input_runtime_lookup(node)


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
