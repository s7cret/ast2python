STATEFUL_TA_FUNCTIONS = {
    "sma",
    "ema",
    "rma",
    "atr",
    "rsi",
    "macd",
    "dmi",
    "supertrend",
    "stoch",
    "adx",
    "wma",
    "vwma",
    "hma",
    "vwap",
    "roc",
    "mom",
    "sar",
    "obv",
    "stdev",
    "variance",
    "dev",
    "correlation",
    "cci",
    "mfi",
    "cum",
    "range",
    "tsi",
    "cmo",
    "tr",
    "bb",
    "bbw",
    "kc",
    "kcw",
    "wpr",
    "crossover",
    "crossunder",
}
DECLARATION_CONTEXT_FIELDS = {
    "indicator": {
        "overlay",
        "format",
        "precision",
        "scale",
        "max_bars_back",
        "timeframe",
        "timeframe_gaps",
        "explicit_plot_zorder",
        "max_lines_count",
        "max_labels_count",
        "max_boxes_count",
        "max_polylines_count",
        "dynamic_requests",
    },
    "library": {"dynamic_requests"},
}
STRATEGY_CONTEXT_FIELDS = {
    "initial_capital",
    "currency",
    "default_qty_type",
    "default_qty_value",
    "pyramiding",
    "commission_type",
    "commission_value",
    "slippage",
    "process_orders_on_close",
    "calc_on_order_fills",
    "use_bar_magnifier",
    "backtest_fill_limits_assumption",
    "close_entries_rule",
    "max_bars_back",
    "max_lines_count",
    "max_labels_count",
    "max_boxes_count",
    "calc_on_every_tick",
    "margin_long",
    "margin_short",
    "fill_orders_on_standard_ohlc",
    "risk_free_rate",
}
DECLARATION_CONTEXT_FIELDS["strategy"] = STRATEGY_CONTEXT_FIELDS | {"overlay"}
VISUAL_OBJECT_PRODUCERS = {"line.new", "label.new", "box.new", "table.new"}
VISUAL_OBJECT_METHOD_PREFIXES = ("line.", "label.", "box.", "table.")
VISUAL_STATEMENT_CALLS = {
    "plot",
    "plotshape",
    "plotchar",
    "hline",
    "fill",
    "bgcolor",
    "barcolor",
    "table.cell",
}
FUNCTION_DECLARATIONS = {"FunctionDeclaration", "FunctionDecl", "FunctionDefinition"}
METHOD_DECLARATIONS = {"MethodDeclaration", "MethodDecl"}
UDT_DECLARATIONS = {"TypeDeclaration", "UserTypeDeclaration", "UDTDeclaration"}
ENUM_DECLARATIONS = {"EnumDeclaration", "EnumDecl"}
BUILTIN_SERIES = {"open", "high", "low", "close", "volume", "time", "time_close"}
TIME_COMPONENT_BUILTINS = {"year", "month", "dayofmonth", "dayofweek", "hour", "minute", "second"}
DERIVED_BUILTIN_SERIES = {"hl2", "hlc3", "ohlc4", "hlcc4"}
ATR_SHORTHANDS = {"ta.atr20": 20, "ta.atr30": 30, "ta.atr50": 50}
LOWER_TF_PURE_CALL_PREFIXES = ("math.",)
LOWER_TF_IMMUTABLE_SCALAR_BASE_TYPES = {
    "int",
    "float",
    "bool",
    "string",
    "color",
    "timeframe",
    "session",
    "time",
}
REFERENCE_TYPES = {"array", "map", "matrix", "PineArray", "PineMap", "PineMatrix"}
STRATEGY_CALLS_P0 = {
    "strategy.entry",
    "strategy.order",
    "strategy.exit",
    "strategy.close",
    "strategy.close_all",
    "strategy.cancel",
    "strategy.cancel_all",
}
STRATEGY_READONLY_FIELDS = {
    "equity",
    "netprofit",
    "openprofit",
    "grossprofit",
    "grossloss",
    "position_size",
    "position_avg_price",
    "opentrades",
    "closedtrades",
    "wintrades",
    "losstrades",
    "eventrades",
    "max_drawdown",
    "max_runup",
}
