from __future__ import annotations

import ast
import copy
from types import ModuleType
from typing import Any

from ast2python.translator import translate_ast
from tests.contract_metadata import with_valid_producer_metadata


def _span(
    line: int,
    start_column: int,
    end_column: int,
    *,
    start_offset: int = 0,
    end_offset: int = 1,
) -> dict[str, dict[str, int]]:
    return {
        "start": {"line": line, "column": start_column, "offset": start_offset},
        "end": {"line": line, "column": end_column, "offset": end_offset},
    }


def _ident(name: str) -> dict[str, Any]:
    return {"kind": "Identifier", "name": name}


def _callee(name: str) -> dict[str, Any]:
    parts = name.split(".")
    node = _ident(parts[0])
    for part in parts[1:]:
        node = {"kind": "MemberAccessExpr", "object": node, "member": part}
    return node


def _lit(value: object, literal_type: str) -> dict[str, Any]:
    return {"kind": "Literal", "literal_type": literal_type, "value": value}


def _arg(value: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    return {"kind": "Argument", "name": name, "value": value}


def _call(
    name: str,
    arguments: list[dict[str, Any]],
    *,
    span: dict[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "kind": "CallExpr",
        "callee": _callee(name),
        "arguments": arguments,
    }
    if span is not None:
        node["span"] = span
    if source is not None:
        node["source"] = source
    return node


def _program(
    kind: str,
    items: list[dict[str, Any]],
    *,
    declaration_span: dict[str, Any] | None = None,
) -> dict[str, Any]:
    declaration_call = _call(
        kind,
        [_arg(_lit("RC.4 Wave 0", "string"))],
        span=declaration_span,
        source=f'{kind}("RC.4 Wave 0")',
    )
    return with_valid_producer_metadata(
        {
            "kind": "Program",
            "language": "pine",
            "version": 6,
            "declaration": {
                "kind": "DeclarationStatement",
                "script_type": kind,
                "call": declaration_call,
            },
            "items": items,
        }
    )


def _generated_class(code: str, name: str) -> ast.ClassDef:
    tree = ast.parse(code)
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def _method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef:
    return next(
        node for node in class_node.body if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _python_call_name(node: ast.Call) -> str | None:
    current: ast.expr = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    return ".".join([current.id, *reversed(parts)])


def test_generated_strategy_constructor_injects_execution_context_without_generic_fallback() -> (
    None
):
    result = translate_ast(_program("strategy", []), module_name="rc4_execution_context")
    generated = _generated_class(result.code, "GeneratedStrategy")
    constructor = _method(generated, "__init__")
    parameter_names = {
        argument.arg
        for argument in [
            *constructor.args.posonlyargs,
            *constructor.args.args,
            *constructor.args.kwonlyargs,
        ]
    }
    execution_context_reads = [
        node
        for node in ast.walk(constructor)
        if isinstance(node, ast.Name)
        and node.id == "execution_context"
        and isinstance(node.ctx, ast.Load)
    ]
    parents = {
        child: parent for parent in ast.walk(constructor) for child in ast.iter_child_nodes(parent)
    }
    generic_context_calls: list[ast.Call] = []
    for node in ast.walk(constructor):
        if not isinstance(node, ast.Call) or _python_call_name(node) != "StrategyContext":
            continue
        if node.args or node.keywords:
            continue
        ancestor = parents.get(node)
        is_conditional = False
        while ancestor is not None:
            if isinstance(ancestor, (ast.If, ast.IfExp)):
                is_conditional = True
                break
            ancestor = parents.get(ancestor)
        if not is_conditional:
            generic_context_calls.append(node)

    blockers: list[str] = []
    if "execution_context" not in parameter_names:
        blockers.append("GeneratedStrategy.__init__ has no execution_context parameter")
    if not execution_context_reads:
        blockers.append("the injected execution_context is not consumed")
    if generic_context_calls:
        blockers.append("StrategyContext() is still constructed unconditionally")
    assert not blockers, "; ".join(blockers)


def test_injected_execution_context_binds_complete_intent_source_provenance() -> None:
    entry_call = _call(
        "strategy.entry",
        [
            _arg(_lit("L", "string")),
            _arg(
                {
                    "kind": "MemberAccessExpr",
                    "object": _ident("strategy"),
                    "member": "long",
                }
            ),
        ],
        span=_span(3, 0, 32, start_offset=40, end_offset=72),
    )
    result = translate_ast(
        _program(
            "strategy",
            [{"kind": "ExpressionStatement", "expression": entry_call}],
        ),
        module_name="rc4_intent_source_provenance",
    )

    assert "self._execution_context_source_hash" in result.code
    assert "'known': True" in result.code
    for field in (
        "start_offset",
        "end_offset",
        "start_line",
        "start_col",
        "end_line",
        "end_col",
    ):
        assert repr(field) in result.code


def test_generated_strategy_checkpoint_round_trip_restores_all_owned_state() -> None:
    counter = {
        "kind": "VarDeclaration",
        "name": "counter",
        "initializer": _ident("close"),
        "mode": "var",
    }
    entry = {
        "kind": "ExpressionStatement",
        "expression": _call(
            "strategy.entry",
            [
                _arg(_lit("L", "string")),
                _arg({"kind": "MemberAccessExpr", "object": _ident("strategy"), "member": "long"}),
            ],
        ),
    }
    result = translate_ast(
        _program("strategy", [counter, entry]), module_name="rc4_generated_checkpoint"
    )
    generated = _generated_class(result.code, "GeneratedStrategy")
    method_names = {node.name for node in generated.body if isinstance(node, ast.FunctionDef)}
    hook_pair = next(
        (
            pair
            for pair in (
                ("export_checkpoint", "restore_checkpoint"),
                ("export_state", "restore_state"),
            )
            if set(pair) <= method_names
        ),
        None,
    )
    assert hook_pair is not None, (
        "GeneratedStrategy must expose paired checkpoint export/restore hooks; "
        f"emitted methods were {sorted(method_names)}"
    )

    class StatefulProbe:
        def __init__(self, state: dict[str, Any]) -> None:
            self.state = copy.deepcopy(state)

        def export_state(self) -> dict[str, Any]:
            return copy.deepcopy(self.state)

        def restore_state(self, state: dict[str, Any]) -> None:
            self.state = copy.deepcopy(state)

        export_checkpoint = export_state
        restore_checkpoint = restore_state

    module = ModuleType("rc4_generated_checkpoint")
    exec(compile(result.code, "rc4_generated_checkpoint.py", "exec"), module.__dict__)
    script = object.__new__(module.GeneratedStrategy)
    script.rt = StatefulProbe(
        {"series": {"counter": {"current": 7, "history": [3, 5]}}, "varip": {"ticks": 2}}
    )
    script.ctx = StatefulProbe(
        {
            "pending_orders": [{"id": "L", "qty": 1}],
            "positions": {"L": 1},
            "fills": [{"order_id": "L", "price": 7}],
            "equity": 100_007,
        }
    )
    script._var_initialized = {"counter": True}
    script._series_initialized = True

    export_name, restore_name = hook_pair
    checkpoint = getattr(script, export_name)()
    expected_runtime = copy.deepcopy(script.rt.state)
    expected_strategy = copy.deepcopy(script.ctx.state)
    script.rt.state["series"]["counter"]["current"] = 999
    script.rt.state["varip"]["ticks"] = 999
    script.ctx.state["pending_orders"].clear()
    script.ctx.state["positions"].clear()
    script._var_initialized["counter"] = False
    script._series_initialized = False

    getattr(script, restore_name)(checkpoint)

    assert script._var_initialized == {"counter": True}
    assert script._series_initialized is True
    assert script.rt.state == expected_runtime
    assert script.ctx.state == expected_strategy


def test_nested_pine_runtime_calls_have_distinct_call_level_source_map_records() -> None:
    inner_span = _span(7, 14, 29)
    outer_span = _span(7, 4, 30)
    inner = _call(
        "math.abs",
        [_arg(_ident("close"))],
        span=inner_span,
        source="math.abs(close)",
    )
    outer = _call(
        "math.sqrt",
        [_arg(inner)],
        span=outer_span,
        source="math.sqrt(math.abs(close))",
    )
    result = translate_ast(
        _program(
            "indicator",
            [
                {
                    "kind": "VarDeclaration",
                    "name": "root",
                    "initializer": outer,
                    "span": _span(7, 0, 30),
                    "source": "root = math.sqrt(math.abs(close))",
                }
            ],
        ),
        module_name="rc4_nested_call_source_map",
    )
    generated_tree = ast.parse(result.code)
    outer_runtime_call = next(
        node
        for node in ast.walk(generated_tree)
        if isinstance(node, ast.Call) and _python_call_name(node) == "sqrt"
    )
    inner_runtime_call = next(
        node
        for node in ast.walk(outer_runtime_call)
        if node is not outer_runtime_call and isinstance(node, ast.Call)
    )
    python_lines = {outer_runtime_call.lineno, inner_runtime_call.lineno}
    assert len(python_lines) == 1
    python_line = python_lines.pop()
    mapped_call_spans = {
        (
            entry.get("pine_line"),
            entry.get("pine_column"),
            entry.get("pine_end_line"),
            entry.get("pine_end_column"),
        )
        for entry in result.source_map
        if entry.get("python_line") == python_line
    }
    expected_call_spans = {(7, 4, 7, 30), (7, 14, 7, 29)}
    assert expected_call_spans <= mapped_call_spans, (
        "nested Pine calls sharing one emitted Python line need separate source-map records; "
        f"expected {sorted(expected_call_spans)}, got {sorted(mapped_call_spans)}"
    )


def test_pine_strategy_context_construction_is_not_generic_scaffold_source_map() -> None:
    declaration_span = _span(2, 0, 25)
    result = translate_ast(
        _program("strategy", [], declaration_span=declaration_span),
        module_name="rc4_strategy_context_source_map",
    )
    generated_tree = ast.parse(result.code)
    context_call = next(
        node
        for node in ast.walk(generated_tree)
        if isinstance(node, ast.Call) and _python_call_name(node) == "StrategyContext"
    )
    context_entries = [
        entry
        for entry in result.source_map
        if entry.get("python_line") == context_call.lineno
        and (
            entry.get("pine_line"),
            entry.get("pine_column"),
            entry.get("pine_end_line"),
            entry.get("pine_end_column"),
        )
        == (2, 0, 2, 25)
    ]
    assert context_entries, (
        "StrategyContext construction is Pine-derived from strategy(...), but its source-map "
        "entry does not carry the declaration call span"
    )
    assert all(entry.get("origin") != "generated_runtime_scaffold" for entry in context_entries)
