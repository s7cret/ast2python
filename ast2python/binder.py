from __future__ import annotations

from dataclasses import dataclass

from ast2python.types import QUALIFIER_ORDER, TypeInfo


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    accepted_types: frozenset[str]
    qualifier_max: str = "series"
    required: bool = True


@dataclass(frozen=True)
class SignatureSpec:
    builtin: str
    parameters: tuple[ParameterSpec, ...]
    min_varargs: int = 0
    vararg: ParameterSpec | None = None
    allow_extra_named: frozenset[str] = frozenset()
    codegen_supported: bool = True
    notes: str = ""


NUMERIC = frozenset({"int", "float", "source"})
NUMERIC_OR_BOOL = frozenset({"int", "float", "bool"})
STRING = frozenset({"string"})
BOOL = frozenset({"bool"})
OBJECT_ID = frozenset({"PineObjectId", "line", "label", "box", "table"})
REFERENCE = frozenset({"array", "map", "matrix", "PineArray", "PineMap", "PineMatrix"})
ANY = frozenset(
    {
        "any",
        "object",
        "int",
        "float",
        "bool",
        "string",
        "color",
        "PineObjectId",
        "array",
        "map",
        "matrix",
    }
)


P = ParameterSpec
S = SignatureSpec


# AST2Python's semantic binder matrix is deliberately scoped to names the
# generator lowers or records today. It is not an official/full TradingView Pine
# registry. Entries encode the compile-time contract for this backend so bad
# arity, unknown named args, and qualifier/type mismatches fail closed before
# Python generation can silently diverge.
BUILTIN_SIGNATURES: dict[str, SignatureSpec] = {
    # TA runtime-mode helpers with state ids.
    "ta.ema": S(
        "ta.ema", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple"))
    ),
    "ta.rma": S(
        "ta.rma", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple"))
    ),
    "ta.rsi": S(
        "ta.rsi", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple"))
    ),
    "ta.atr": S("ta.atr", (P("length", frozenset({"int"}), "simple"),)),
    "ta.sma": S(
        "ta.sma", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "series"))
    ),
    "ta.macd": S(
        "ta.macd",
        (
            P("source", NUMERIC, "series"),
            P("fastlen", frozenset({"int"}), "simple"),
            P("slowlen", frozenset({"int"}), "simple"),
            P("siglen", frozenset({"int"}), "simple"),
        ),
    ),
    # Tuple/stateless TA helpers currently lowered directly to PineLib.
    "ta.bb": S(
        "ta.bb",
        (
            P("series", NUMERIC, "series"),
            P("length", frozenset({"int"}), "series"),
            P("mult", NUMERIC, "simple"),
        ),
    ),
    "ta.bbw": S(
        "ta.bbw",
        (
            P("series", NUMERIC, "series"),
            P("length", frozenset({"int"}), "series"),
            P("mult", NUMERIC, "simple"),
        ),
    ),
    "ta.highest": S(
        "ta.highest", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple"))
    ),
    "ta.lowest": S(
        "ta.lowest", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple"))
    ),
    "ta.change": S(
        "ta.change",
        (
            P("source", NUMERIC_OR_BOOL, "series"),
            P("length", frozenset({"int"}), "simple", required=False),
        ),
    ),
    "ta.crossover": S(
        "ta.crossover", (P("source1", NUMERIC, "series"), P("source2", NUMERIC, "series"))
    ),
    "ta.crossunder": S(
        "ta.crossunder", (P("source1", NUMERIC, "series"), P("source2", NUMERIC, "series"))
    ),
    "ta.cross": S("ta.cross", (P("source1", NUMERIC, "series"), P("source2", NUMERIC, "series"))),
    "ta.stdev": S(
        "ta.stdev",
        (
            P("source", NUMERIC, "series"),
            P("length", frozenset({"int"}), "simple"),
            P("biased", BOOL, "simple", required=False),
        ),
    ),
    "ta.variance": S(
        "ta.variance",
        (
            P("source", NUMERIC, "series"),
            P("length", frozenset({"int"}), "simple"),
            P("biased", BOOL, "simple", required=False),
        ),
    ),
    "ta.dev": S(
        "ta.dev", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple"))
    ),
    "ta.wma": S(
        "ta.wma", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple"))
    ),
    "ta.vwma": S(
        "ta.vwma", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple"))
    ),
    "ta.swma": S("ta.swma", (P("source", NUMERIC, "series"),)),
    "ta.alma": S(
        "ta.alma",
        (
            P("series", NUMERIC, "series"),
            P("length", frozenset({"int"}), "simple"),
            P("offset", NUMERIC, "simple"),
            P("sigma", NUMERIC, "simple"),
            P("floor", BOOL, "simple", required=False),
        ),
    ),
    "ta.stoch": S(
        "ta.stoch",
        (
            P("source", NUMERIC, "series"),
            P("high", NUMERIC, "series"),
            P("low", NUMERIC, "series"),
            P("length", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.pivothigh": S(
        "ta.pivothigh",
        (
            P("source", NUMERIC, "series"),
            P("leftbars", frozenset({"int"}), "simple"),
            P("rightbars", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.pivotlow": S(
        "ta.pivotlow",
        (
            P("source", NUMERIC, "series"),
            P("leftbars", frozenset({"int"}), "simple"),
            P("rightbars", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.valuewhen": S(
        "ta.valuewhen",
        (
            P("condition", BOOL, "series"),
            P("source", ANY, "series"),
            P("occurrence", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.barssince": S("ta.barssince", (P("condition", BOOL, "series"),)),
    "ta.linreg": S(
        "ta.linreg",
        (
            P("source", NUMERIC, "series"),
            P("length", frozenset({"int"}), "simple"),
            P("offset", frozenset({"int"}), "simple", required=False),
        ),
    ),
    "ta.percentrank": S(
        "ta.percentrank",
        (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple")),
    ),
    "ta.percentile_nearest_rank": S(
        "ta.percentile_nearest_rank",
        (
            P("source", NUMERIC, "series"),
            P("length", frozenset({"int"}), "simple"),
            P("percentage", NUMERIC, "simple"),
        ),
    ),
    "ta.percentile_linear_interpolation": S(
        "ta.percentile_linear_interpolation",
        (
            P("source", NUMERIC, "series"),
            P("length", frozenset({"int"}), "simple"),
            P("percentage", NUMERIC, "simple"),
        ),
    ),
    "ta.mom": S(
        "ta.mom", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple"))
    ),
    "ta.roc": S(
        "ta.roc", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple"))
    ),
    "ta.correlation": S(
        "ta.correlation",
        (
            P("source1", NUMERIC, "series"),
            P("source2", NUMERIC, "series"),
            P("length", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.rising": S(
        "ta.rising", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple"))
    ),
    "ta.falling": S(
        "ta.falling", (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple"))
    ),
    "ta.vwap": S("ta.vwap", (P("source", NUMERIC, "series"),)),
    "ta.tr": S("tr", (P("handle_na", BOOL, "simple", required=False),)),
    # Known PineLib helpers not safe in current scalar runtime lowering.
    "ta.hma": S(
        "ta.hma",
        (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple")),
    ),
    "ta.dmi": S(
        "ta.dmi",
        (
            P("di_length", frozenset({"int"}), "simple"),
            P("adx_smoothing", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.adx": S(
        "ta.adx",
        (
            P("di_length", frozenset({"int"}), "simple"),
            P("adx_smoothing", frozenset({"int"}), "simple"),
        ),
        codegen_supported=False,
        notes="PineLib adx is batch-only today",
    ),
    "ta.supertrend": S(
        "ta.supertrend",
        (P("factor", NUMERIC, "series"), P("atrPeriod", frozenset({"int"}), "simple")),
    ),
    "ta.sar": S(
        "ta.sar",
        (
            P("start", NUMERIC, "simple", required=False),
            P("inc", NUMERIC, "simple", required=False),
            P("max", NUMERIC, "simple", required=False),
        ),
    ),
    # Pine v6: additional TA function signatures.
    "ta.cum": S(
        "cum",
        (P("source", NUMERIC, "series"),),
    ),
    "ta.range": S(
        "ta_range",
        (
            P("source", NUMERIC, "series"),
            P("length", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.cmo": S(
        "cmo",
        (
            P("source", NUMERIC, "series"),
            P("length", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.tsi": S(
        "tsi",
        (
            P("source", NUMERIC, "series"),
            P("shortLength", frozenset({"int"}), "simple"),
            P("longLength", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.cci": S(
        "ta.cci",
        (
            P("source", NUMERIC, "series"),
            P("length", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.mfi": S(
        "ta.mfi",
        (
            P("source", NUMERIC, "series"),
            P("length", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.highestbars": S(
        "highestbars",
        (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple")),
    ),
    "ta.lowestbars": S(
        "lowestbars",
        (P("source", NUMERIC, "series"), P("length", frozenset({"int"}), "simple")),
    ),
    # math namespace exposed by PineLib and lowered as direct calls.
    **{
        f"math.{name}": S(f"math.{name}", (P("number", NUMERIC, "series"),))
        for name in (
            "abs",
            "sign",
            "sqrt",
            "exp",
            "log",
            "log10",
            "sin",
            "cos",
            "tan",
            "asin",
            "acos",
            "atan",
            "todegrees",
            "toradians",
            "ceil",
            "floor",
            "trunc",
        )
    },
    "math.pow": S("math.pow", (P("base", NUMERIC, "series"), P("exponent", NUMERIC, "series"))),
    "math.round": S(
        "math.round",
        (
            P("number", NUMERIC, "series"),
            P("precision", frozenset({"int"}), "simple", required=False),
        ),
    ),
    "math.min": S("math.min", (), min_varargs=1, vararg=P("number", NUMERIC, "series")),
    "math.max": S("math.max", (), min_varargs=1, vararg=P("number", NUMERIC, "series")),
    "math.avg": S("math.avg", (), min_varargs=1, vararg=P("number", NUMERIC, "series")),
    "math.random": S(
        "math.random",
        (
            P("min", NUMERIC, "simple", required=False),
            P("max", NUMERIC, "simple", required=False),
            P("seed", frozenset({"int"}), "simple", required=False),
        ),
    ),
    # Type-cast builtins (used in Pine v6 with explicit casts).
    "int": S("int", (P("value", NUMERIC_OR_BOOL, "series"),)),
    "float": S("float", (P("value", NUMERIC_OR_BOOL, "series"),)),
    "bool": S("bool", (P("value", ANY, "series"),)),
    "str": S("str", (P("value", ANY, "series"),)),
    # str namespace exposed by PineLib.
    "str.tostring": S(
        "str.tostring", (P("value", ANY, "series"), P("format", STRING, "simple", required=False))
    ),
    "str.tonumber": S("str.tonumber", (P("string", STRING, "series"),)),
    "str.contains": S("str.contains", (P("source", STRING, "series"), P("str", STRING, "simple"))),
    "str.startswith": S(
        "str.startswith", (P("source", STRING, "series"), P("str", STRING, "simple"))
    ),
    "str.endswith": S("str.endswith", (P("source", STRING, "series"), P("str", STRING, "simple"))),
    "str.lower": S("str.lower", (P("source", STRING, "series"),)),
    "str.upper": S("str.upper", (P("source", STRING, "series"),)),
    "str.length": S("str.length", (P("source", STRING, "series"),)),
    "str.substring": S(
        "str.substring",
        (
            P("source", STRING, "series"),
            P("begin_pos", frozenset({"int"}), "simple"),
            P("end_pos", frozenset({"int"}), "simple", required=False),
        ),
    ),
    "str.replace": S(
        "str.replace",
        (
            P("source", STRING, "series"),
            P("target", STRING, "simple"),
            P("replacement", STRING, "simple"),
            P("occurrence", frozenset({"int"}), "simple", required=False),
        ),
    ),
    # requests lowered by AST2Python.
    "request.security": S(
        "request.security",
        (
            P("symbol", frozenset({"string", "object"}), "series"),
            P("timeframe", frozenset({"string", "object"}), "series"),
            P("expression", ANY, "series"),
            P("gaps", STRING, "simple", required=False),
            P("lookahead", STRING, "simple", required=False),
            P("ignore_invalid_symbol", BOOL, "simple", required=False),
            P("currency", STRING, "simple", required=False),
            P("calc_bars_count", frozenset({"int"}), "simple", required=False),
        ),
    ),
    "request.security_lower_tf": S(
        "request.security_lower_tf",
        (
            P("symbol", frozenset({"string", "object"}), "series"),
            P("timeframe", frozenset({"string", "object"}), "series"),
            P("expression", ANY, "series"),
            P("ignore_invalid_symbol", BOOL, "simple", required=False),
            P("currency", STRING, "simple", required=False),
            P("calc_bars_count", frozenset({"int"}), "simple", required=False),
        ),
        notes="PineLib runtime_contract_v1.4 bounded lower-timeframe array slice",
    ),
    # Strategy P0 calls lowered to StrategyContext.
    "strategy.entry": S(
        "strategy.entry",
        (
            P("id", STRING, "simple"),
            P("direction", STRING, "simple"),
            P("qty", NUMERIC, "series", required=False),
            P("limit", NUMERIC, "series", required=False),
            P("stop", NUMERIC, "series", required=False),
            P("comment", STRING, "series", required=False),
        ),
    ),
    "strategy.order": S(
        "strategy.order",
        (
            P("id", STRING, "simple"),
            P("direction", STRING, "simple"),
            P("qty", NUMERIC, "series", required=False),
            P("limit", NUMERIC, "series", required=False),
            P("stop", NUMERIC, "series", required=False),
            P("comment", STRING, "simple", required=False),
            P("oca_name", STRING, "simple", required=False),
            P("oca_type", STRING, "simple", required=False),
        ),
    ),
    "strategy.exit": S(
        "strategy.exit",
        (
            P("id", STRING, "simple"),
            P("from_entry", STRING, "simple", required=False),
            P("qty", NUMERIC, "series", required=False),
            P("qty_percent", NUMERIC, "series", required=False),
            P("limit", NUMERIC, "series", required=False),
            P("stop", NUMERIC, "series", required=False),
            P("profit", NUMERIC, "series", required=False),
            P("loss", NUMERIC, "series", required=False),
            P("trail_price", NUMERIC, "series", required=False),
            P("trail_points", NUMERIC, "series", required=False),
            P("trail_offset", NUMERIC, "series", required=False),
            P("comment", STRING, "simple", required=False),
            P("oca_name", STRING, "simple", required=False),
            P("oca_type", STRING, "simple", required=False),
        ),
    ),
    "strategy.close": S(
        "strategy.close",
        (
            P("id", STRING, "simple"),
            P("qty", NUMERIC, "series", required=False),
            P("qty_percent", NUMERIC, "series", required=False),
            P("comment", STRING, "simple", required=False),
            P("immediately", BOOL, "simple", required=False),
        ),
    ),
    "strategy.close_all": S(
        "strategy.close_all",
        (
            P("immediately", BOOL, "simple", required=False),
            P("comment", STRING, "simple", required=False),
        ),
        allow_extra_named=frozenset({"comment"}),
    ),
    "strategy.cancel": S("strategy.cancel", (P("id", STRING, "simple"),)),
    "strategy.cancel_all": S("strategy.cancel_all", ()),
    # strategy.closedtrades namespace — index-based trade history accessor
    "strategy.closedtrades.entry_price": S(
        "strategy.closedtrades.entry_price",
        (P("index", NUMERIC, "simple"),),
    ),
    "strategy.closedtrades.exit_price": S(
        "strategy.closedtrades.exit_price",
        (P("index", NUMERIC, "simple"),),
    ),
    "strategy.closedtrades.entry_time": S(
        "strategy.closedtrades.entry_time",
        (P("index", NUMERIC, "simple"),),
    ),
    "strategy.closedtrades.exit_time": S(
        "strategy.closedtrades.exit_time",
        (P("index", NUMERIC, "simple"),),
    ),
    "strategy.closedtrades.profit": S(
        "strategy.closedtrades.profit",
        (P("index", NUMERIC, "simple"),),
    ),
    "strategy.closedtrades.size": S(
        "strategy.closedtrades.size",
        (P("index", NUMERIC, "simple"),),
    ),
    "strategy.closedtrades.max_drawdown": S(
        "strategy.closedtrades.max_drawdown",
        (P("index", NUMERIC, "simple"),),
    ),
    "strategy.closedtrades.max_runup": S(
        "strategy.closedtrades.max_runup",
        (P("index", NUMERIC, "simple"),),
    ),
    # strategy.opentrades namespace
    "strategy.opentrades.entry_price": S(
        "strategy.opentrades.entry_price",
        (P("index", NUMERIC, "simple"),),
    ),
    "strategy.opentrades.profit": S(
        "strategy.opentrades.profit",
        (P("index", NUMERIC, "simple"),),
    ),
    "strategy.opentrades.size": S(
        "strategy.opentrades.size",
        (P("index", NUMERIC, "simple"),),
    ),
    "strategy.opentrades.max_drawdown": S(
        "strategy.opentrades.max_drawdown",
        (P("index", NUMERIC, "simple"),),
    ),
    "strategy.opentrades.max_runup": S(
        "strategy.opentrades.max_runup",
        (P("index", NUMERIC, "simple"),),
    ),
    # strategy.risk namespace
    "strategy.risk.allow_entry_in": S(
        "strategy.risk.allow_entry_in",
        (P("direction", STRING, "simple"),),
    ),
    "strategy.risk.max_drawdown": S(
        "strategy.risk.max_drawdown",
        (P("value", NUMERIC, "simple"), P("type", STRING, "simple")),
    ),
    "strategy.risk.max_intraday_loss": S(
        "strategy.risk.max_intraday_loss",
        (P("value", NUMERIC, "simple"), P("type", STRING, "simple")),
    ),
    "strategy.risk.max_position_size": S(
        "strategy.risk.max_position_size",
        (P("value", NUMERIC, "simple"), P("type", STRING, "simple")),
    ),
    # Visual recorder calls. Optional style/text/color args are admitted only by name.
    "plot": S(
        "plot",
        (
            P("series", ANY, "series"),
            P("title", STRING, "simple", required=False),
            P("color", ANY, "series", required=False),
        ),
        allow_extra_named=frozenset(
            {
                "linewidth",
                "style",
                "trackprice",
                "histbase",
                "offset",
                "join",
                "editable",
                "show_last",
                "display",
                "format",
                "precision",
                "force_overlay",
            }
        ),
    ),
    "plotshape": S(
        "plotshape",
        (P("series", ANY, "series"),),
        allow_extra_named=frozenset(
            {
                "title",
                "style",
                "location",
                "color",
                "size",
                "text",
                "textcolor",
                "offset",
                "show_last",
                "display",
            }
        ),
    ),
    "plotchar": S(
        "plotchar",
        (P("series", ANY, "series"),),
        allow_extra_named=frozenset(
            {
                "title",
                "char",
                "location",
                "color",
                "size",
                "text",
                "textcolor",
                "offset",
                "show_last",
                "display",
            }
        ),
    ),
    "hline": S(
        "hline",
        (P("price", NUMERIC, "series"),),
        allow_extra_named=frozenset(
            {"title", "color", "linestyle", "linewidth", "editable", "display"}
        ),
    ),
    "fill": S(
        "fill",
        (P("hline1", ANY, "series"), P("hline2", ANY, "series")),
        allow_extra_named=frozenset({"color", "title", "editable", "fillgaps", "display"}),
    ),
    "bgcolor": S(
        "bgcolor",
        (P("color", ANY, "series"),),
        allow_extra_named=frozenset({"offset", "editable", "show_last", "title", "display"}),
    ),
    "barcolor": S(
        "barcolor",
        (P("color", ANY, "series"),),
        allow_extra_named=frozenset({"offset", "editable", "show_last", "title", "display"}),
    ),
    "line.new": S(
        "line.new",
        (
            P("x1", frozenset({"int"}), "series"),
            P("y1", NUMERIC, "series"),
            P("x2", frozenset({"int"}), "series"),
            P("y2", NUMERIC, "series"),
        ),
        allow_extra_named=frozenset({"xloc", "extend", "color", "style", "width", "force_overlay"}),
    ),
    "line.set_xy1": S(
        "line.set_xy1",
        (
            P("id", OBJECT_ID, "series"),
            P("x", frozenset({"int"}), "series"),
            P("y", NUMERIC, "series"),
        ),
    ),
    "line.set_xy2": S(
        "line.set_xy2",
        (
            P("id", OBJECT_ID, "series"),
            P("x", frozenset({"int"}), "series"),
            P("y", NUMERIC, "series"),
        ),
    ),
    "line.delete": S("line.delete", (P("id", OBJECT_ID, "series"),)),
    "label.new": S(
        "label.new",
        (
            P("x", frozenset({"int"}), "series"),
            P("y", NUMERIC, "series"),
            P("text", STRING, "series", required=False),
        ),
        allow_extra_named=frozenset(
            {
                "xloc",
                "yloc",
                "color",
                "style",
                "textcolor",
                "size",
                "textalign",
                "tooltip",
                "force_overlay",
            }
        ),
    ),
    "label.delete": S("label.delete", (P("id", OBJECT_ID, "series"),)),
    "box.new": S(
        "box.new",
        (
            P("left", frozenset({"int"}), "series"),
            P("top", NUMERIC, "series"),
            P("right", frozenset({"int"}), "series"),
            P("bottom", NUMERIC, "series"),
        ),
        allow_extra_named=frozenset(
            {
                "border_color",
                "border_width",
                "border_style",
                "extend",
                "xloc",
                "bgcolor",
                "text",
                "text_size",
                "text_color",
                "text_halign",
                "text_valign",
                "force_overlay",
            }
        ),
    ),
    "box.delete": S("box.delete", (P("id", OBJECT_ID, "series"),)),
    "table.new": S(
        "table.new",
        (
            P("position", STRING, "simple"),
            P("columns", frozenset({"int"}), "simple"),
            P("rows", frozenset({"int"}), "simple"),
        ),
        allow_extra_named=frozenset(
            {
                "bgcolor",
                "frame_color",
                "frame_width",
                "border_color",
                "border_width",
                "force_overlay",
            }
        ),
    ),
    "table.cell": S(
        "table.cell",
        (
            P("table_id", OBJECT_ID, "series"),
            P("column", frozenset({"int"}), "simple"),
            P("row", frozenset({"int"}), "simple"),
            P("text", STRING, "series"),
        ),
        allow_extra_named=frozenset(
            {
                "width",
                "height",
                "text_color",
                "text_halign",
                "text_valign",
                "text_size",
                "bgcolor",
                "tooltip",
            }
        ),
    ),
    # Reference helpers lowered to PineLib reference containers.
    "array.new": S("array.new", (P("initial_value", ANY, "series", required=False),)),
    "array.from": S("array.from", (), min_varargs=0, vararg=P("value", ANY, "series")),
    "array.new_float": S(
        "array.new_float",
        (
            P("initial", ANY, "series", required=False),
            P("max_size", frozenset({"int"}), "simple", required=False),
        ),
    ),
    "array.new_int": S(
        "array.new_int",
        (
            P("initial", ANY, "series", required=False),
            P("max_size", frozenset({"int"}), "simple", required=False),
        ),
    ),
    "array.new_bool": S(
        "array.new_bool",
        (
            P("initial", ANY, "series", required=False),
            P("max_size", frozenset({"int"}), "simple", required=False),
        ),
    ),
    "array.new_string": S(
        "array.new_string",
        (
            P("initial", ANY, "series", required=False),
            P("max_size", frozenset({"int"}), "simple", required=False),
        ),
    ),
    "array.new_color": S(
        "array.new_color",
        (
            P("initial", ANY, "series", required=False),
            P("max_size", frozenset({"int"}), "simple", required=False),
        ),
    ),
    "array.push": S("array.push", (P("id", REFERENCE, "series"), P("value", ANY, "series"))),
    "array.get": S(
        "array.get", (P("id", REFERENCE, "series"), P("index", frozenset({"int"}), "series"))
    ),
    "array.set": S(
        "array.set",
        (
            P("id", REFERENCE, "series"),
            P("index", frozenset({"int"}), "series"),
            P("value", ANY, "series"),
        ),
    ),
    "array.size": S("array.size", (P("id", REFERENCE, "series"),)),
    "array.copy": S("array.copy", (P("id", REFERENCE, "series"),)),
    "array.shift": S(
        "array.shift",
        (
            P("id", REFERENCE, "series"),
            P("index", frozenset({"int"}), "series", required=False),
        ),
    ),
    "array.sort": S(
        "array.sort",
        (
            P("id", REFERENCE, "series"),
            P("order", frozenset({"string"}), "simple", required=False),
        ),
    ),
    "array.avg": S("array.avg", (P("id", REFERENCE, "series"),)),
    "array.sum": S("array.sum", (P("id", REFERENCE, "series"),)),
    "array.min": S("array.min", (P("id", REFERENCE, "series"),)),
    "array.max": S("array.max", (P("id", REFERENCE, "series"),)),
    "map.new": S("map.new", ()),
    "map.put": S(
        "map.put",
        (P("id", REFERENCE, "series"), P("key", ANY, "series"), P("value", ANY, "series")),
    ),
    "map.get": S(
        "map.get",
        (
            P("id", REFERENCE, "series"),
            P("key", ANY, "series"),
            P("default", ANY, "series", required=False),
        ),
    ),
    "map.remove": S("map.remove", (P("id", REFERENCE, "series"), P("key", ANY, "series"))),
    "map.copy": S("map.copy", (P("id", REFERENCE, "series"),)),
    "matrix.new": S(
        "matrix.new",
        (
            P("rows", frozenset({"int"}), "simple"),
            P("columns", frozenset({"int"}), "simple"),
            P("initial_value", ANY, "series", required=False),
        ),
    ),
    "matrix.get": S(
        "matrix.get",
        (
            P("id", REFERENCE, "series"),
            P("row", frozenset({"int"}), "series"),
            P("column", frozenset({"int"}), "series"),
        ),
    ),
    "matrix.set": S(
        "matrix.set",
        (
            P("id", REFERENCE, "series"),
            P("row", frozenset({"int"}), "series"),
            P("column", frozenset({"int"}), "series"),
            P("value", ANY, "series"),
        ),
    ),
    "matrix.copy": S("matrix.copy", (P("id", REFERENCE, "series"),)),
}


def qualifier_leq(actual: str, maximum: str) -> bool:
    return QUALIFIER_ORDER.get(actual, 99) <= QUALIFIER_ORDER.get(maximum, 99)


def type_matches(actual: str, accepted: frozenset[str]) -> bool:
    if "any" in accepted:
        return True
    if actual in accepted:
        return True
    if actual == "object":
        return "object" in accepted or "any" in accepted
    if actual in {"line", "label", "box", "table"} and "PineObjectId" in accepted:
        return True
    if (
        actual in {"PineArray", "PineMap", "PineMatrix"}
        and actual.removeprefix("Pine").lower() in accepted
    ):
        return True
    return actual == "int" and "float" in accepted


def _allows_untyped_numeric_parameter(
    builtin: str, expected: ParameterSpec, actual: TypeInfo
) -> bool:
    # Pine2AST leaves untyped user-function parameters as object/simple. Keep this
    # escape hatch tied to that origin and to the HMA shape that needs it.
    if actual.origin != "untyped_param" or actual.base_type != "object" or actual.qualifier != "simple":
        return False
    if builtin == "math.sqrt" and expected.name == "number":
        return True
    if not builtin.startswith("ta."):
        return False
    if expected.name in {"source", "source1", "source2", "series"}:
        return expected.accepted_types <= NUMERIC
    if expected.name in {"length", "fastlen", "slowlen", "siglen"}:
        return expected.accepted_types == frozenset({"int"})
    return False


def _parameter_slots(spec: SignatureSpec, arg_count: int) -> tuple[ParameterSpec, ...]:
    if spec.vararg is None:
        return spec.parameters
    extras = max(0, arg_count - len(spec.parameters))
    return spec.parameters + tuple(spec.vararg for _ in range(extras))


def bind_builtin_call(builtin: str, arg_types: list[tuple[str | None, TypeInfo]]) -> list[str]:
    """Return human-readable binding errors for a known builtin call."""
    spec = BUILTIN_SIGNATURES.get(builtin)
    if spec is None:
        return [f"{builtin} has no AST2Python semantic binder signature"]
    errors: list[str] = []
    required = sum(1 for param in spec.parameters if param.required)
    if len(arg_types) < max(required, spec.min_varargs):
        errors.append(
            f"{builtin} expects at least {max(required, spec.min_varargs)} arguments, got {len(arg_types)}"  # noqa: E501
        )
    if spec.vararg is None and len(arg_types) > len(spec.parameters):
        errors.append(
            f"{builtin} expects at most {len(spec.parameters)} arguments, got {len(arg_types)}"
        )
    name_to_index = {param.name: index for index, param in enumerate(spec.parameters)}
    slots = _parameter_slots(spec, len(arg_types))
    used: set[int] = set()
    seen_named = False
    for index, (arg_name, actual) in enumerate(arg_types):
        param_index = index
        if arg_name is not None:
            seen_named = True
            if arg_name in name_to_index:
                param_index = name_to_index[arg_name]
            elif arg_name in spec.allow_extra_named:
                continue
            else:
                errors.append(f"{builtin} does not accept named argument {arg_name!r}")
                continue
        elif seen_named:
            errors.append(f"{builtin} positional argument follows named argument")
        if param_index >= len(slots):
            continue
        if param_index in used and spec.vararg is None:
            errors.append(
                f"{builtin} argument {slots[param_index].name!r} is provided more than once"
            )
            continue
        used.add(param_index)
        expected = slots[param_index]
        if not type_matches(
            actual.base_type, expected.accepted_types
        ) and not _allows_untyped_numeric_parameter(builtin, expected, actual):
            accepted = "/".join(sorted(expected.accepted_types))
            errors.append(f"{builtin}.{expected.name} expects {accepted}, got {actual.base_type}")
        if not qualifier_leq(actual.qualifier, expected.qualifier_max):
            errors.append(
                f"{builtin}.{expected.name} expects qualifier <= {expected.qualifier_max}, got {actual.qualifier}"  # noqa: E501
            )
    for index, param in enumerate(spec.parameters):
        if param.required and index not in used and len(arg_types) >= required:
            errors.append(f"{builtin} missing required argument {param.name!r}")
    if not spec.codegen_supported:
        errors.append(
            f"{builtin} is signature-known but unsupported by current AST2Python codegen: {spec.notes}"  # noqa: E501
        )
    return errors
