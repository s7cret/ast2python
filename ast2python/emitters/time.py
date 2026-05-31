"""Pine time and timestamp call emitters."""
from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from typing import TYPE_CHECKING, Any

from ast2python.errors import UnsupportedBuiltinError

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTNode


DATE_HELPERS = {
    "year",
    "month",
    "weekofyear",
    "dayofmonth",
    "dayofweek",
    "hour",
    "minute",
    "second",
}


class PineTimeEmitter:
    """Lower Pine time-family builtins through the owning translator."""

    def __init__(self, translator: Any) -> None:
        self.translator = translator

    def translate_date_helper_call(
        self, name: str, node: ASTNode, *, runtime_expr: str
    ) -> str:
        translator = self.translator
        args = []
        for arg_name, arg in translator._call_arguments(node):
            # Pine calendar helpers accept an optional timestamp, but PineLib v1 derives
            # calendar fields from the active runtime bar. Preserve supported named
            # arguments such as timezone and avoid emitting incompatible positionals.
            if arg_name is None:
                continue
            rendered = translator.translate_expression(arg, runtime_expr=runtime_expr)
            args.append(f"{arg_name}={rendered}")
        args.append(f"runtime={runtime_expr}")
        translator.ctx.coverage.builtin(name)
        return f"{runtime_expr}.timefunc.{name}({', '.join(args)})"

    def translate_timestamp_call(self, node: ASTNode) -> str:
        """Lower Pine timestamp() to Unix milliseconds integer."""
        translator = self.translator
        arguments = translator._call_arguments(node)
        if not arguments:
            raise UnsupportedBuiltinError("timestamp requires at least one argument")
        arg_name, arg_expr = arguments[0]
        if arg_name is not None:
            raise UnsupportedBuiltinError("timestamp does not support named arguments")

        rendered = translator.translate_expression(arg_expr)
        literal_value = translator._literal_or_rendered(arg_expr, rendered)

        if len(arguments) > 1:
            if not isinstance(literal_value, str):
                raise UnsupportedBuiltinError(
                    "timestamp first argument must be a timezone string, "
                    f"got {type(literal_value).__name__}"
                )
            return self._translate_timestamp_components(literal_value, arguments[1:])

        if not isinstance(literal_value, str):
            raise UnsupportedBuiltinError(
                f"timestamp argument must be a string literal, got {type(literal_value).__name__}"
            )
        unix_ms = self._parse_pine_timestamp(literal_value)
        translator.ctx.coverage.builtin("timestamp")
        return str(unix_ms)

    def _translate_timestamp_components(
        self, timezone_str: str, components: list[tuple[str | None, ASTNode]]
    ) -> str:
        translator = self.translator
        if len(components) < 5:
            raise UnsupportedBuiltinError(
                "timestamp with timezone requires at least 6 arguments "
                "(timezone, year, month, day, hour, minute), "
                f"got {len(components) + 1}"
            )

        component_values: list[int | str] = []
        all_literal = True
        for name, node in components[:6]:
            if name is not None:
                raise UnsupportedBuiltinError("timestamp component arguments must be positional")
            rendered = translator.translate_expression(node)
            val = translator._literal_or_rendered(node, rendered)
            if isinstance(val, (int, float)):
                component_values.append(int(val))
            else:
                all_literal = False
                component_values.append(rendered)
        while len(component_values) < 6:
            component_values.append(0)

        if all_literal:
            year, month, day, hour, minute, second = component_values
            try:
                dt = datetime(
                    int(year),
                    int(month),
                    int(day),
                    int(hour),
                    int(minute),
                    int(second),
                    tzinfo=_timezone_for_name(timezone_str),
                )
                unix_ms = int(dt.timestamp() * 1000)
            except (ValueError, OSError) as exc:
                raise UnsupportedBuiltinError(
                    f"timestamp: invalid date/time components: {exc}"
                ) from exc
            translator.ctx.coverage.builtin("timestamp")
            return str(unix_ms)

        args = [f"{timezone_str!r}"] + [str(c) for c in component_values[:6]]
        translator.ctx.coverage.builtin("timestamp")
        return f"self.rt.timefunc.timestamp_components({', '.join(args)})"

    def _parse_pine_timestamp(self, value: str) -> int:
        formats = [
            "%Y-%m-%d %H:%M:%S %z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M %z",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(value, fmt)
                return int(dt.timestamp() * 1000)
            except ValueError:
                continue
        raise UnsupportedBuiltinError(
            f"timestamp: unsupported date format {value!r}. "
            'Supported: "YYYY-MM-DD HH:MM:SS +ZZZZ", '
            '"YYYY-MM-DDTHH:MM:SS+ZZZZ", "YYYY-MM-DD HH:MM +ZZZZ"'
        )

    def translate_time_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        translator = self.translator
        func_name = "time" if name == "time" else "time_close"
        args = []
        for arg_name, arg in translator._call_arguments(node):
            rendered = translator.translate_expression(arg, runtime_expr=runtime_expr)
            args.append(rendered if arg_name is None else f"{arg_name}={rendered}")
        args.append(f"runtime={runtime_expr}")
        translator.ctx.coverage.builtin(name)
        return f"{runtime_expr}.timefunc.{func_name}({', '.join(args)})"


def _timezone_for_name(timezone_str: str) -> tzinfo:
    if timezone_str == "UTC":
        return UTC
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError as exc:
        raise UnsupportedBuiltinError(
            "timestamp timezone names require Python zoneinfo support"
        ) from exc
    try:
        return ZoneInfo(timezone_str)
    except ZoneInfoNotFoundError as exc:
        raise UnsupportedBuiltinError(
            f"timestamp: unsupported timezone {timezone_str!r}"
        ) from exc
