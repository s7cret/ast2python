"""Translator type inference helpers."""

from __future__ import annotations

from typing import Any

from ast2python.ast.schema import ASTNode
from ast2python.errors import ScopeResolutionError
from ast2python.translator_constants import (
    BUILTIN_SERIES,
    DERIVED_BUILTIN_SERIES,
    REFERENCE_TYPES,
    VISUAL_OBJECT_PRODUCERS,
)
from ast2python.translator_mixins.metadata import member_chain
from ast2python.types import TypeInfo, join_qualifiers, make_type_info


def infer_type_info(translator: Any, node: ASTNode | None) -> TypeInfo:
    if node is None:
        return make_type_info("object", "simple")
    if node.kind == "Literal":
        literal_type = node.field("literal_type")
        base = (
            "object"
            if literal_type == "na"
            else ("float" if literal_type == "float" else str(literal_type or "object"))
        )
        return make_type_info(base, "const", can_be_na=base != "bool")
    if node.kind == "Identifier":
        name = str(node.field("name"))
        if name in BUILTIN_SERIES:
            return make_type_info(
                {"time": "int", "time_close": "int"}.get(name, "float"),
                "series",
                is_series=True,
            )
        if name in DERIVED_BUILTIN_SERIES:
            return make_type_info("float", "series", is_series=True)
        if name == "bar_index":
            return make_type_info("int", "series", is_series=True, can_be_na=False)
        if name == "na":
            return make_type_info("object", "const")
        try:
            info = translator.ctx.resolve_var(name)
            if info.type_info is not None:
                if info.declaration_kind == "input":
                    return make_type_info(
                        info.type_info.base_type, "input", can_be_na=info.type_info.can_be_na
                    )
                # If type_info is "object" (e.g. from `na` initializer) but a concrete
                # type_ref was declared (e.g. "float" from `var float x = na`), use
                # the declared type_ref so that math/series bindings succeed.
                # NOTE: visual-object type_refs (line/label/box/table/PineObjectId) are
                # excluded from this branch so they fall through to the dedicated
                # PineObjectId branch below (line 3109). This preserves correct binding
                # for visual method calls (line.set_xy1, label.set_text, etc.).
                if (
                    info.type_info.base_type == "object"
                    and info.type_ref is not None
                    and info.type_ref not in {"line", "label", "box", "table", "PineObjectId", "array", "matrix", "map"}
                ):
                    return make_type_info(
                        info.type_ref, info.qualifier, is_series=info.is_series
                    )
                # Visual object types (line/label/box/table): use PineObjectId base type
                # so that binding for visual methods (line.set_xy1, etc.) succeeds.
                if info.type_ref in {"line", "label", "box", "table", "PineObjectId"}:
                    return make_type_info("PineObjectId", info.qualifier, is_series=info.is_series)
                return info.type_info
            return make_type_info(info.type_ref, info.qualifier, is_series=info.is_series)
        except ScopeResolutionError:
            return make_type_info("object", "simple")
    if node.kind == "MemberAccessExpr":
        chain = member_chain(node)
        if chain in {
            "strategy.long",
            "strategy.short",
            "strategy.oca.cancel",
            "strategy.oca.reduce",
        }:
            return make_type_info("string", "const", can_be_na=False)
        if chain is not None and chain.startswith("syminfo."):
            member = chain.split(".", 1)[1]
            # syminfo.mintick and syminfo.pointvalue are float, rest are string
            if member in ("mintick", "pointvalue"):
                return make_type_info("float", "simple", can_be_na=False)
            return make_type_info("string", "simple", can_be_na=False)
        if chain is not None and chain.startswith(
            (
                "barmerge.",
                "display.",
                "currency.",
                "location.",
                "shape.",
                "size.",
                "position.",
                "plot.style_",
                "format.",
            )
        ):
            return make_type_info("string", "const", can_be_na=False)
        if chain is not None and chain.startswith("color."):
            return make_type_info("color", "const", can_be_na=False)
        # Handle ta.hl2, ta.hlc3, ta.ohlc4, ta.hlcc4 used as call arguments (e.g. ta.cci(ta.hlc3, 20)).
        if chain is not None and chain.startswith("ta."):
            member = chain.split(".", 1)[1]
            if member in DERIVED_BUILTIN_SERIES:
                return make_type_info("float", "series", is_series=True)
    if node.kind == "Call":
        callee = node.child("callee")
        if callee is not None and callee.kind == "MemberAccess":
            obj = callee.child("object")
            member = callee.field("member")
            if obj is not None and str(obj.field("name")) == "ta" and member in DERIVED_BUILTIN_SERIES:
                # ta.hlc3(), ta.hl2() as explicit function calls → float series
                return make_type_info("float", "series", is_series=True)
        # Handle time() and time_close() function calls (e.g. time("D"), time_close("W"))
        # These return int series, not input
        if callee is not None and callee.kind == "Identifier":
            fn_name = str(callee.field("name"))
            if fn_name in ("time", "time_close") and translator._call_arguments(node):
                return make_type_info("int", "series", is_series=True, can_be_na=True)
    if translator._is_input_call(node):
        callee = node.child("callee")
        chain = None if callee is None else member_chain(callee)
        if chain is None:
            return make_type_info("object", "input")
        info_type = chain.split(".", 1)[1]
        base = {
            "timeframe": "string",
            "session": "string",
            "time": "int",
            "symbol": "string",  # symbol name is a string for request.security
        }.get(info_type, info_type)
        # time(timeframe) and time_close(timeframe) return series, not input
        if info_type in ("time", "time_close") and translator._call_arguments(node):
            return make_type_info(base, "series", is_series=True, can_be_na=True)
        return make_type_info(base, "input", can_be_na=base != "bool")
    if node.kind == "BinaryExpr":
        left = translator._infer_type_info(node.child("left"))
        right = translator._infer_type_info(node.child("right"))
        op = node.field("op")
        if op in {"and", "or", "==", "!=", ">", ">=", "<", "<="}:
            return make_type_info(
                "bool", join_qualifiers(left.qualifier, right.qualifier), can_be_na=False
            )
        # String concatenation: if either side is string, result is string
        if op == "+" and (
            left.base_type == "string" or right.base_type == "string"
        ):
            return make_type_info(
                "string", join_qualifiers(left.qualifier, right.qualifier)
            )
        base = "float" if "float" in {left.base_type, right.base_type} else left.base_type
        return make_type_info(base, join_qualifiers(left.qualifier, right.qualifier))
    if node.kind == "UnaryExpr":
        return translator._infer_type_info(node.child("operand"))
    if node.kind == "ConditionalExpr":
        condition = translator._infer_type_info(node.child("condition"))
        if_true = translator._infer_type_info(node.child("then") or node.child("if_true"))
        if_false = translator._infer_type_info(node.child("else") or node.child("if_false"))
        base = (
            "float" if "float" in {if_true.base_type, if_false.base_type} else if_true.base_type
        )
        return make_type_info(
            base,
            join_qualifiers(condition.qualifier, if_true.qualifier, if_false.qualifier),
            can_be_na=base != "bool",
        )
    if node.kind == "TupleExpr":
        items = [translator._infer_type_info(item) for item in node.children("elements", "items")]
        qualifier = join_qualifiers(*(item.qualifier for item in items)) if items else "const"
        return make_type_info("tuple", qualifier)
    if node.kind in {"HistoryRefExpr", "HistoryReference", "SubscriptExpr", "IndexExpr"}:
        base_info = translator._infer_type_info(
            node.child("base")
            or node.child("object")
            or node.child("target")
            or node.child("expression")
        )
        return make_type_info(
            base_info.base_type,
            "series",
            is_series=True,
            can_be_na=base_info.base_type != "bool",
        )
    if node.kind == "CallExpr":
        callee = node.child("callee")
        chain = None if callee is None else member_chain(callee)
        # na is a Literal(literal_type='na') in Pine, not an Identifier.
        # Handle it here so the na() type inference works correctly.
        if callee is not None and callee.kind == "Literal" and callee.field("literal_type") == "na":
            args = translator._call_arguments(node)
            if args:
                first_type = translator._infer_type_info(args[0][1])
                return make_type_info("bool", first_type.qualifier, can_be_na=False)
            return make_type_info("bool", "simple", can_be_na=False)
        if chain in {"input.bool"}:
            return make_type_info("bool", "input", can_be_na=False)
        if chain in {"input.int"}:
            return make_type_info("int", "input", can_be_na=False)
        if chain in {
            "input.float",
            "ta.ema",
            "ta.rma",
            "ta.atr",
            "ta.rsi",
            "ta.sma",
            "ta.highest",
            "ta.lowest",
            "ta.change",
            "ta.stdev",
            "ta.variance",
            "ta.dev",
            "ta.wma",
            "ta.vwma",
            "ta.swma",
            "ta.alma",
            "ta.bbw",
            "ta.stoch",
            "ta.valuewhen",
            "ta.linreg",
            "ta.percentrank",
            "ta.percentile_nearest_rank",
            "ta.percentile_linear_interpolation",
            "ta.mom",
            "ta.roc",
            "ta.cci",
            "ta.mfi",
            "ta.cmo",
            "ta.tsi",
            "ta.range",
            "ta.correlation",
            "ta.vwap",
            "ta.kc",
            "ta.kcw",
            "ta.wpr",
            "ta.cum",
            "ta.sar",
            "ta.pivothigh",
            "ta.pivotlow",
        }:
            return make_type_info("float", "series", is_series=chain.startswith("ta."))
        if chain == "str.tonumber":
            return make_type_info("float", "series", is_series=True)
        if chain in {"str.tostring", "str.substring", "str.lower", "str.upper", "str.replace", "str.format"}:
            return make_type_info("string", "series", is_series=True)
        if chain in {"str.contains", "str.startswith", "str.endswith"}:
            return make_type_info("bool", "series", is_series=True)
        if chain in {"str.length", "str.pos"}:
            return make_type_info("int", "series", is_series=True)
        if chain in {"ta.crossover", "ta.crossunder", "ta.cross", "ta.rising", "ta.falling"}:
            return make_type_info("bool", "series", is_series=True, can_be_na=False)
        if chain == "ta.barssince":
            return make_type_info("int", "series", is_series=True)
        if chain in {"ta.bb", "ta.macd"}:
            return make_type_info("tuple", "series", is_series=True)
        if chain == "request.security_lower_tf":
            return make_type_info("array", "series", is_history_allowed=False)
        # request.financial/economic/currency_rate/earnings/dividends/splits
        # all return float series (financial/economic data is time-series)
        if chain and chain.startswith("request."):
            return make_type_info("float", "series", is_series=True)
        # request.security returns the same type as its expression argument (arg index 2)
        if chain == "request.security" and translator._call_arguments(node):
            args = translator._call_arguments(node)
            if len(args) >= 3:
                expr_node = args[2][1]
                expr_callee = expr_node.child("callee") if expr_node.kind == "CallExpr" else None
                expr_chain = member_chain(expr_callee) if expr_callee else None
                if expr_chain in translator.TUPLE_RETURNING_BUILTINS:
                    # request.security with a tuple-returning builtin expression preserves tuple type
                    return make_type_info("tuple", "series", is_series=True, can_be_na=True)
                expr_type = translator._infer_type_info(expr_node)
                return make_type_info(expr_type.base_type, "series", is_series=True, can_be_na=expr_type.can_be_na)
        if chain in {"input.string", "input.timeframe", "input.session"}:
            return make_type_info("string", "input", can_be_na=False)
        if chain == "input.time":
            return make_type_info("int", "input", can_be_na=False)
        # time() and time_close() with a timeframe arg return int series, not input
        if chain in ("time", "time_close") and translator._call_arguments(node):
            return make_type_info("int", "series", is_series=True, can_be_na=True)
        if chain == "input.source":
            return make_type_info("float", "input")
        if chain in {"na"}:
            args = translator._call_arguments(node)
            if args:
                first_type = translator._infer_type_info(args[0][1])
                return make_type_info("bool", first_type.qualifier, can_be_na=False)
            return make_type_info("bool", "simple", can_be_na=False)
        # nz and fixnan preserve the type of the first argument.
        if chain in {"nz", "fixnan"}:
            first_arg = node.child("arguments") or node.child("args")
            if first_arg is not None:
                args = list(first_arg) if hasattr(first_arg, "__iter__") else [first_arg]
                if args:
                    first_type = translator._infer_type_info(args[0])
                    return make_type_info(
                        first_type.base_type if first_type.base_type not in {"object", "na"} else "float",
                        "series",
                        is_series=True,
                    )
            return make_type_info("float", "series", is_series=True)
        if chain in {"math.min", "math.max"}:
            arg_infos = [
                translator._infer_type_info(arg) for _, arg in translator._call_arguments(node)
            ]
            qualifier = join_qualifiers(*(info.qualifier for info in arg_infos))
            base = "int" if arg_infos and all(info.base_type == "int" for info in arg_infos) else "float"
            return make_type_info(base, qualifier, is_series=qualifier == "series")
        # math.* functions return a numeric value with the strongest argument qualifier.
        if chain and chain.startswith("math."):
            arg_infos = [
                translator._infer_type_info(arg) for _, arg in translator._call_arguments(node)
            ]
            qualifier = join_qualifiers(*(info.qualifier for info in arg_infos))
            return make_type_info("float", qualifier, is_series=qualifier == "series")
        # Type-cast builtins return their respective types.
        if chain == "int":
            arg_infos = [
                translator._infer_type_info(arg) for _, arg in translator._call_arguments(node)
            ]
            qualifier = join_qualifiers(*(info.qualifier for info in arg_infos))
            return make_type_info("int", qualifier, is_series=qualifier == "series")
        if chain == "float":
            return make_type_info("float", "series", is_series=True)
        if chain == "bool":
            return make_type_info("bool", "series", is_series=True)
        if chain == "str":
            return make_type_info("string", "series", is_series=True)
        if chain in VISUAL_OBJECT_PRODUCERS:
            return make_type_info("PineObjectId", "series")
        # Explicit array method type inference — before the catch-all.
        # array.size returns int series (the array length).
        if chain == "array.size":
            return make_type_info("int", "series", is_series=True)
        # array.get returns the element at index — a float scalar series.
        if chain == "array.get":
            return make_type_info("float", "series", is_series=True)
        # array.from returns a new array reference.
        if chain == "array.from":
            return make_type_info("array", "series", is_series=True, is_history_allowed=False)
        # array.copy returns a copy of the array reference.
        if chain == "array.copy":
            return make_type_info("array", "series", is_series=True, is_history_allowed=False)
        # matrix.get returns a scalar float series (element at row/col) — supports history.
        if chain == "matrix.get":
            return make_type_info("float", "series", is_series=True, is_history_allowed=True)
        # map.get returns a scalar float series (value for key) — supports history.
        if chain == "map.get":
            return make_type_info("float", "series", is_series=True, is_history_allowed=True)
        if isinstance(chain, str) and chain.startswith(("array.", "map.", "matrix.")):
            return make_type_info(
                chain.split(".", 1)[0], "series", is_series=True, is_history_allowed=False
            )
    explicit = translator._type_ref_name(node)
    if explicit in REFERENCE_TYPES:
        return make_type_info(str(explicit), "series", is_series=True, is_history_allowed=False)
    return make_type_info("object", "simple")
