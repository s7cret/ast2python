from __future__ import annotations

from ast2python import call_handlers
from ast2python.emitters.inputs import INPUT_CALLS
from ast2python.emitters.time import DATE_HELPERS

CALL_EXACT: dict[str, call_handlers.ExactCallHandler] = {
    "request.security": call_handlers.request_security,
    "request.security_lower_tf": call_handlers.request_security_lower_tf,
    "request.footprint": call_handlers.request_footprint,
    "timestamp": call_handlers.timestamp,
    "time": call_handlers.builtin_time_exact,
    "time_close": call_handlers.builtin_time_close_exact,
    "timeframe.change": call_handlers.timeframe_change_exact,
    "na": call_handlers.na,
    "nz": call_handlers.nz,
    "fixnan": call_handlers.fixnan,
    "color.new": call_handlers.color_new,
    "alert": call_handlers.alert,
    "alertcondition": call_handlers.alertcondition,
    "strategy.long": call_handlers.strategy_long,
    "strategy.short": call_handlers.strategy_short,
}

for _input_call in INPUT_CALLS:
    CALL_EXACT[_input_call] = call_handlers.input_runtime

for _date_helper in DATE_HELPERS:
    CALL_EXACT[_date_helper] = call_handlers.make_date_helper(_date_helper)

CALL_PREFIX: list[tuple[str, call_handlers.PrefixCallHandler]] = [
    ("request.", call_handlers.unsupported_request),
    ("ta.", call_handlers.builtin_ta),
    ("math.", call_handlers.builtin_math),
    ("str.", call_handlers.builtin_str),
    ("array.", call_handlers.builtin_ref),
    ("map.", call_handlers.builtin_ref),
    ("matrix.", call_handlers.builtin_ref),
    ("strategy.", call_handlers.builtin_strategy_prefix),
]
