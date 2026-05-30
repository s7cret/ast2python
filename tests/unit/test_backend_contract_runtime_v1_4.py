from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

PINELIB_ROOT = Path(__file__).resolve().parents[3] / "pinelib"
if str(PINELIB_ROOT) not in sys.path:
    sys.path.insert(0, str(PINELIB_ROOT))

import pytest  # noqa: E402
from pinelib.core import Bar, PineRuntime, SymbolInfo, TimeframeInfo, na  # noqa: E402
from pinelib.request.providers import InMemoryDataProvider  # noqa: E402

from ast2python.errors import TypeResolutionError  # noqa: E402
from ast2python.translator import translate_ast  # noqa: E402
from tests.contract_metadata import with_valid_producer_metadata  # noqa: E402


def decl(kind: str = "indicator") -> dict:
    return {
        "kind": "DeclarationStatement",
        "script_type": kind,
        "call": {
            "kind": "CallExpr",
            "callee": {"kind": "Identifier", "name": kind},
            "arguments": [{"kind": "Argument", "name": None, "value": lit("contract", "string")}],
        },
    }


def lit(value, typ: str = "int") -> dict:
    return {"kind": "Literal", "literal_type": typ, "value": value}


def ident(name: str) -> dict:
    return {"kind": "Identifier", "name": name}


def member(obj, name: str) -> dict:
    return {
        "kind": "MemberAccessExpr",
        "object": obj if isinstance(obj, dict) else ident(obj),
        "member": name,
    }


def arg(value, name=None) -> dict:
    return {"kind": "Argument", "name": name, "value": value}


def call(name: str, args=None) -> dict:
    callee = (
        ident(name) if "." not in name else member(name.split(".", 1)[0], name.split(".", 1)[1])
    )
    return {"kind": "CallExpr", "callee": callee, "arguments": args or []}


def var(name: str, initializer: dict, **extra) -> dict:
    return {"kind": "VarDeclaration", "name": name, "initializer": initializer, **extra}


def expr(expression: dict) -> dict:
    return {"kind": "ExpressionStatement", "expression": expression}


def program(items, kind: str = "indicator") -> dict:
    return with_valid_producer_metadata({
        "kind": "Program",
        "language": "pine",
        "version": 6,
        "declaration": decl(kind),
        "items": items,
    })


def load_generated(code: str, name: str = "generated_contract") -> ModuleType:
    module = ModuleType(name)
    exec(compile(code, f"{name}.py", "exec"), module.__dict__)
    return module


def runtime(provider=None) -> PineRuntime:
    return PineRuntime(
        SymbolInfo(tickerid="AAPL", timezone="UTC", session="0000-2359"),
        TimeframeInfo.from_string("1"),
        data_provider=provider,
    )


def bars() -> list[Bar]:
    return [
        Bar(time=0, time_close=59_999, open=10, high=11, low=9, close=10, volume=100),
        Bar(time=60_000, time_close=119_999, open=20, high=21, low=19, close=20, volume=200),
    ]


def test_run_owns_full_bar_lifecycle_history_commit_and_scalar_current_close():
    p = program(
        [
            var("x", ident("close")),
            var("prev", {"kind": "HistoryRefExpr", "base": ident("x"), "offset": lit(1)}),
        ]
    )
    result = translate_ast(p, module_name="history_contract")
    assert ".begin_bar(" in result.code and ".end_bar(" in result.code
    assert "self.x.set_current(self.rt.close.current)" in result.code
    mod = load_generated(result.code, "history_contract")
    rt = runtime()
    script = mod.GeneratedIndicator(runtime=rt)
    snapshots = script.run(bars())
    assert [snap["bar_index"] for snap in snapshots] == [0, 1]
    assert rt.series_registry["x"]._history == [10, 20]
    assert rt.series_registry["prev"]._history == [na, 10]


def test_request_security_lowers_to_pinelib_function_and_executes():
    provider = InMemoryDataProvider(
        {
            ("AAPL", "D"): [
                Bar(time=0, time_close=119_999, open=100, high=101, low=99, close=100, volume=1)
            ],
        }
    )
    p = program(
        [
            var(
                "htf",
                call(
                    "request.security",
                    [arg(lit("AAPL", "string")), arg(lit("D", "string")), arg(ident("close"))],
                ),
            ),
        ]
    )
    result = translate_ast(p, module_name="request_contract")
    assert "request_security(" in result.code
    assert ".request.security" not in result.code
    mod = load_generated(result.code, "request_contract")
    rt = runtime(provider)
    mod.GeneratedIndicator(runtime=rt).run(bars())
    assert rt.series_registry["htf"]._history == [na, 100]


def test_visual_strategy_operator_input_time_and_stateful_ta_smoke_without_attribute_errors():
    visual = program(
        [
            var(
                "ln",
                call(
                    "line.new", [arg(lit(0)), arg(ident("close")), arg(lit(1)), arg(ident("close"))]
                ),
                type_ref={"kind": "TypeRef", "name": "line"},
                mode="var",
            ),
            expr(
                call(
                    "line.set_xy1", [arg(ident("ln")), arg(ident("bar_index")), arg(ident("close"))]
                )
            ),
            expr(call("plot", [arg(ident("close"))])),
        ]
    )
    mod = load_generated(
        translate_ast(visual, module_name="visual_contract").code, "visual_contract"
    )
    rt = runtime()
    mod.GeneratedIndicator(runtime=rt).run(bars())
    assert len(rt.visual.events) >= 2

    strategy = program(
        [expr(call("strategy.entry", [arg(lit("L", "string")), arg(member("strategy", "long"))]))],
        kind="strategy",
    )
    smod = load_generated(
        translate_ast(strategy, module_name="strategy_contract").code, "strategy_contract"
    )
    srt = runtime()
    script = smod.GeneratedStrategy(runtime=srt)
    script.run([bars()[0]])
    assert script.ctx.pending_orders and script.ctx.pending_orders[0].id == "L"

    operator = program(
        [
            var("bad", {"kind": "BinaryExpr", "op": "+", "left": ident("na"), "right": lit(1)}),
            var("cmp", {"kind": "BinaryExpr", "op": ">", "left": ident("na"), "right": lit(1)}),
            var("inp", call("input.int", [arg(lit(5)), arg(lit("Length", "string"), "title")])),
            var("t", call("time", [arg(lit("1", "string")), arg(lit("0000-2359", "string"))])),
            var("avg", call("ta.sma", [arg(ident("close")), arg(lit(2))])),
        ]
    )
    omod = load_generated(
        translate_ast(operator, module_name="operator_contract").code, "operator_contract"
    )
    ort = runtime()
    omod.GeneratedIndicator(runtime=ort).run(bars())
    assert ort.series_registry["bad"]._history == [na, na]
    assert ort.series_registry["cmp"]._history == [False, False]
    assert ort.series_registry["inp"]._history == [5, 5]
    assert ort.series_registry["avg"]._history[1] == 15


def test_strategy_default_qty_type_constants_lower_to_runtime_strings():
    p = with_valid_producer_metadata({
        "kind": "Program",
        "language": "pine",
        "version": 6,
        "declaration": {
            "kind": "DeclarationStatement",
            "script_type": "strategy",
            "call": {
                "kind": "CallExpr",
                "callee": ident("strategy"),
                "arguments": [
                    arg(lit("qty contract", "string")),
                    arg(member("strategy", "cash"), "default_qty_type"),
                    arg(lit(100), "default_qty_value"),
                ],
            },
        },
        "items": [],
    })
    result = translate_ast(p, module_name="strategy_qty_type_contract")

    assert 'default_qty_type="cash"' in result.code
    assert "strategy.cash" not in result.code


def test_ta_cross_helpers_receive_series_objects_not_current_scalars():
    p = program(
        [
            var("fast", call("ta.sma", [arg(ident("close")), arg(lit(2))])),
            var("slow", call("ta.sma", [arg(ident("close")), arg(lit(3))])),
            var("xup", call("ta.crossover", [arg(ident("fast")), arg(ident("slow"))])),
            var("xdn", call("ta.crossunder", [arg(ident("fast")), arg(ident("slow"))])),
        ]
    )
    result = translate_ast(p, module_name="ta_cross_series_contract")

    assert "crossover(self.fast, self.slow, runtime=self.rt" in result.code
    assert "crossunder(self.fast, self.slow, runtime=self.rt" in result.code
    assert "state_id=" in result.code
    assert "crossover(self.fast.current, self.slow.current)" not in result.code


def test_bool_na_helpers_are_compile_time_diagnostics():
    p = program(
        [
            var("b", lit(True, "bool"), type_ref={"kind": "TypeRef", "name": "bool"}),
            var("bad", call("nz", [arg(ident("b"))])),
        ]
    )
    with pytest.raises(TypeResolutionError):
        translate_ast(p, module_name="bool_nz_contract")


def test_timeframe_period_and_na_time_call_lower_to_runtime_contract():
    p = program(
        [
            var(
                "in_sess",
                call(
                    "na",
                    [
                        arg(
                            call(
                                "time",
                                [
                                    arg(member("timeframe", "period")),
                                    arg(lit("0930-1600", "string")),
                                    arg(lit("America/New_York", "string")),
                                ],
                            )
                        )
                    ],
                ),
            )
        ]
    )
    result = translate_ast(p, module_name="timeframe_period_session_contract")

    assert "from pinelib.core import" in result.code and "is_na" in result.code
    assert "self.rt.timeframe.value" in result.code
    assert "self.rt.timeframe.period" not in result.code


def test_varip_local_simulation_lowers_to_runtime_varip_state_and_executes():
    p = program(
        [
            var("ticks", lit(0), mode="varip"),
            {"kind": "Reassignment", "target": ident("ticks"), "op": ":=", "value": {"kind": "BinaryExpr", "left": ident("ticks"), "op": "+", "right": lit(1)}},
        ],
        kind="strategy",
    )
    result = translate_ast(
        p,
        module_name="varip_contract",
        compile_profile="diagnostic",
        allow_realtime_local_simulation=True,
    )
    assert "get_varip_state" in result.code
    assert "self.rt.varip_state" in result.code
    assert result.metadata["parity_safe"] is False
    assert "varip_local_simulation" in result.metadata["unsupported_features"]
    mod = load_generated(result.code, "varip_contract")
    rt = runtime()
    script = mod.GeneratedStrategy(runtime=rt)
    snapshots = script.run(bars())
    assert [snap["bar_index"] for snap in snapshots] == [0, 1]
    assert rt.series_registry["ticks"]._history == [1, 2]
    assert rt.varip_state["global:ticks"] == 2


def test_varip_realtime_rollback_checkpoint_preserves_generated_varip_state():
    p = program(
        [
            var("ticks", lit(0), mode="varip"),
            {"kind": "Reassignment", "target": ident("ticks"), "op": ":=", "value": {"kind": "BinaryExpr", "left": ident("ticks"), "op": "+", "right": lit(1)}},
        ],
        kind="strategy",
    )
    result = translate_ast(
        p,
        module_name="varip_rollback_contract",
        compile_profile="diagnostic",
        allow_realtime_local_simulation=True,
    )
    mod = load_generated(result.code, "varip_rollback_contract")
    rt = runtime()
    script = mod.GeneratedStrategy(runtime=rt)
    bar = bars()[0]
    rt.begin_realtime_bar(bar)
    script._process_bar(bar)
    checkpoint = rt.export_state(include_varip=False)

    script._process_bar(bar)
    assert rt.varip_state["global:ticks"] == 2

    rt.restore_state(checkpoint)
    assert rt.varip_state["global:ticks"] == 2
    assert rt.series_registry["ticks"].current == 1
