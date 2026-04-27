from __future__ import annotations

import ast as pyast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ast2python.ast.schema import ASTNode, ASTProgram, ensure_program_node, load_ast, validate_ast
from ast2python.context import TranslationContext, VariableInfo
from ast2python.diagnostics import (
    CONTRACT_VERSION_MISMATCH,
    UNKNOWN_OVERLOAD,
    UNSUPPORTED_DECLARATION_ARG,
    VISUAL_OBJECT_USED_AS_VALUE,
    WARNING_NESTED_SECURITY,
    Diagnostic,
    Severity,
)
from ast2python.emitter import CodeEmitter
from ast2python.errors import (
    ScopeResolutionError,
    TypeResolutionError,
    UnsupportedBuiltinError,
    UnsupportedNodeError,
    ValidationError,
)
from ast2python.state import state_id_for_call
from ast2python.version import RUNTIME_CONTRACT_VERSION, __version__

STATEFUL_TA_FUNCTIONS = {"ema", "rma", "atr", "rsi", "macd", "supertrend", "bb"}
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
    "max_bars_back",
}
VISUAL_OBJECT_PRODUCERS = {"line.new", "label.new", "box.new", "table.new"}
VISUAL_STATEMENT_CALLS = {"plot", "plotshape", "plotchar", "hline", "fill", "bgcolor", "barcolor"}
BUILTIN_SERIES = {"open", "high", "low", "close", "volume", "time", "time_close"}


def member_chain(node: ASTNode) -> str | None:
    if node.kind == "Identifier":
        name = node.field("name")
        return name if isinstance(name, str) else None
    if node.kind != "MemberAccessExpr":
        return None
    base = node.child("object")
    member = node.field("member")
    if base is None or not isinstance(member, str):
        return None
    prefix = member_chain(base)
    if prefix is None:
        return None
    return f"{prefix}.{member}"


def literal_value(node: ASTNode) -> Any:
    return node.field("value")


@dataclass
class TranslationResult:
    code: str
    metadata: dict[str, Any]
    source_map: list[dict[str, Any]]
    coverage: dict[str, Any]
    diagnostics: list[Diagnostic]
    module_name: str

    def write_to(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        py_path = output / f"{self.module_name}.py"
        meta_path = output / f"{self.module_name}.meta.json"
        sourcemap_path = output / f"{self.module_name}.sourcemap.json"
        coverage_path = output / f"{self.module_name}.coverage.json"
        py_path.write_text(self.code, encoding="utf-8")
        meta_path.write_text(json.dumps(self.metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        sourcemap_path.write_text(json.dumps(self.source_map, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        coverage_path.write_text(json.dumps(self.coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "python": py_path,
            "metadata": meta_path,
            "source_map": sourcemap_path,
            "coverage": coverage_path,
        }


class Translator:
    def __init__(self, *, strict: bool = False, emit_source_comments: bool = True) -> None:
        self.strict = strict
        self.emit_source_comments = emit_source_comments
        self.ctx = TranslationContext(strict=strict)
        self.emitter = CodeEmitter(self.ctx.source_map, emit_source_comments=emit_source_comments)
        self.global_series: list[tuple[VariableInfo, str]] = []
        self.input_series: list[tuple[VariableInfo, str, dict[str, Any]]] = []
        self.var_flags: list[VariableInfo] = []

    def translate_file(self, path: str | Path, *, module_name: str | None = None) -> TranslationResult:
        return self.translate_program(load_ast(path), module_name=module_name or Path(path).stem)

    def translate_program(self, program: ASTProgram | dict[str, Any], *, module_name: str | None = None) -> TranslationResult:
        if isinstance(program, dict):
            program = ensure_program_node(program)
        problems = validate_ast(program)
        if problems:
            raise ValidationError("; ".join(problems))
        for _ in program.descendants():
            self.ctx.coverage.seen()
        declaration = program.declaration
        if declaration is None:
            raise ValidationError("Program declaration is required")
        mode = declaration.field("script_type", default="indicator")
        self.ctx.mode = str(mode)
        title = self._extract_declaration_title(declaration)
        result_module_name = module_name or self.ctx.naming.reserve(title or "generated")
        self._emit_module(program, declaration, title=title, module_name=result_module_name)
        metadata = self._build_metadata(program, title=title, module_name=result_module_name)
        return TranslationResult(
            code=self.emitter.render(),
            metadata=metadata,
            source_map=self.ctx.source_map.to_list(),
            coverage=self.ctx.coverage.to_dict(),
            diagnostics=self.ctx.diagnostics,
            module_name=result_module_name,
        )

    def _emit_module(self, program: ASTProgram, declaration: ASTNode, *, title: str, module_name: str) -> None:
        self._collect_globals(program)
        self._declare_base_imports()
        self._declare_dynamic_imports(program)
        self.emitter.line("# Generated by AST2Python")
        self.emitter.line(f"# Pine runtime contract: {RUNTIME_CONTRACT_VERSION}")
        self.emitter.line(f'# Source: {module_name}.pine')
        self.emitter.line()
        self.emitter.line("from __future__ import annotations")
        self.emitter.line()
        for line in self.ctx.imports.render():
            self.emitter.line(line)
        self.emitter.line()
        self.emitter.line(f'REQUIRED_RUNTIME_CONTRACT = "{RUNTIME_CONTRACT_VERSION}"')
        self.emitter.line()
        class_name = {
            "strategy": "GeneratedStrategy",
            "indicator": "GeneratedIndicator",
            "library": "GeneratedLibrary",
        }.get(self.ctx.mode, "GeneratedScript")
        self.emitter.line(f"class {class_name}:")
        self.emitter.indent()
        self.emitter.line('"""')
        self.emitter.line(f"Generated from Pine declaration: {title}")
        self.emitter.line('"""')
        self.emitter.line()
        self._emit_init(declaration)
        self.emitter.line()
        self._emit_run()
        self.emitter.line()
        self._emit_snapshot()
        if self.ctx.mode != "library":
            self.emitter.line()
            self._emit_process_bar(program)
        self.emitter.dedent()

    def _declare_base_imports(self) -> None:
        self.ctx.imports.require_from("ast2python.errors", "RuntimeContractError")
        self.ctx.imports.require_from("pinelib.core", "PineRuntime")
        self.ctx.imports.require_from("pinelib.core", "na")
        self.ctx.imports.require_from("pinelib.core", "pine_bool")
        if self.ctx.mode == "strategy":
            self.ctx.imports.require_from("pinelib.strategy", "StrategyContext")

    def _declare_dynamic_imports(self, program: ASTProgram) -> None:
        """Predeclare imports needed by generated statements before rendering the header."""
        for node in program.descendants():
            if node.kind == "ForRangeStructure":
                self.ctx.imports.require_from("pinelib.core", "pine_range")
            if node.kind == "MemberAccessExpr":
                chain = member_chain(node)
                if chain is not None and chain.startswith("color."):
                    self.ctx.imports.require_from("pinelib.colors", "color", alias="pine_color")
            if node.kind != "CallExpr":
                continue
            callee = node.child("callee")
            chain = None if callee is None else member_chain(callee)
            if chain is None:
                continue
            if chain.startswith("ta."):
                self.ctx.imports.require_from("pinelib.ta", chain.split(".", 1)[1])
            elif chain.startswith("math."):
                self.ctx.imports.require_from("pinelib.math", chain.split(".", 1)[1])
            elif chain.startswith("str."):
                self.ctx.imports.require_from("pinelib.strings", "str")

    def _emit_init(self, declaration: ASTNode) -> None:
        self.emitter.line("def __init__(self, params=None, runtime=None):")
        self.emitter.indent()
        self.emitter.line("self.params = params or {}")
        self.emitter.line("self.rt = runtime")
        self.emitter.line("if self.rt is None:")
        self.emitter.indent()
        self.emitter.line('raise RuntimeContractError("runtime is required for generated modules")')
        self.emitter.dedent()
        self.emitter.line("if getattr(self.rt, 'contract_version', None) != REQUIRED_RUNTIME_CONTRACT:")
        self.emitter.indent()
        self.emitter.line(
            'raise RuntimeContractError('
            f'f"{CONTRACT_VERSION_MISMATCH}: requires runtime contract '
            '{REQUIRED_RUNTIME_CONTRACT}, got '
            '{getattr(self.rt, \'contract_version\', None)}"'
            ')'
        )
        self.emitter.dedent()
        if self.ctx.mode == "strategy":
            self._emit_strategy_context(declaration)
        else:
            self.emitter.line("self.ctx = None")
        self.emitter.line("self._var_initialized = {}")
        self.emitter.line("self._init_series()")
        self.emitter.line("self._init_inputs()")
        self.emitter.dedent()
        self.emitter.line()
        self.emitter.line("def _init_series(self):")
        self.emitter.indent()
        if not self.global_series:
            self.emitter.line("pass")
        for info, dtype in self.global_series:
            self.emitter.line(f'self.{info.py_name} = self.rt.series("{info.py_name}", dtype="{dtype}")')
            self.emitter.line(f'self._var_initialized["{info.py_name}"] = False')
        self.emitter.dedent()
        self.emitter.line()
        self.emitter.line("def _init_inputs(self):")
        self.emitter.indent()
        if not self.input_series:
            self.emitter.line("pass")
        for info, dtype, meta in self.input_series:
            default = meta["default_python"]
            self.emitter.line(f'self.{info.py_name} = self.rt.series("{info.py_name}", dtype="{dtype}")')
            self.emitter.line(f'self.{info.py_name}.set_current(self.params.get("{info.pine_name}", {default}))')
        self.emitter.dedent()

    def _emit_strategy_context(self, declaration: ASTNode) -> None:
        kwargs = self._strategy_context_kwargs(declaration)
        if kwargs:
            self.emitter.line("self.ctx = StrategyContext(")
            self.emitter.indent()
            for key, value in kwargs:
                self.emitter.line(f"{key}={value},")
            self.emitter.dedent()
            self.emitter.line(")")
        else:
            self.emitter.line("self.ctx = StrategyContext()")

    def _emit_run(self) -> None:
        self.emitter.line("def run(self, bars):")
        self.emitter.indent()
        self.emitter.line("results = []")
        self.emitter.line("for bar in bars:")
        self.emitter.indent()
        self.emitter.line("self.rt.begin_bar(bar)")
        if self.ctx.mode == "library":
            self.emitter.line("results.append(None)")
        else:
            self.emitter.line("self._process_bar(bar)")
            self.emitter.line("self.rt.end_bar()")
            self.emitter.line("results.append(self._snapshot())")
        self.emitter.dedent()
        self.emitter.line("return results")
        self.emitter.dedent()

    def _emit_snapshot(self) -> None:
        self.emitter.line("def _snapshot(self):")
        self.emitter.indent()
        self.emitter.line("return {")
        self.emitter.indent()
        self.emitter.line("'bar_index': getattr(self.rt, 'bar_index', None),")
        if self.ctx.mode == "strategy":
            self.emitter.line("'position_size': getattr(self.ctx, 'position_size', None),")
        self.emitter.dedent()
        self.emitter.line("}")
        self.emitter.dedent()

    def _emit_process_bar(self, program: ASTProgram) -> None:
        self.emitter.line("def _process_bar(self, bar):")
        self.emitter.indent()
        if not program.items:
            self.emitter.line("pass")
        for item in program.items:
            self._emit_statement(item)
        self.emitter.dedent()

    def _collect_globals(self, program: ASTProgram) -> None:
        for item in program.items:
            if item.kind == "TupleDeclaration":
                initializer = item.child("initializer") or item.child("value")
                for name in self._tuple_targets(item):
                    if name == "_":
                        continue
                    info = self.ctx.declare_var(
                        name,
                        type_ref=None,
                        qualifier=item.field("explicit_qualifier"),
                        declaration_kind=str(item.field("mode") or "normal"),
                        is_series=True,
                        is_mutable=True,
                        loc=item.loc,
                    )
                    self.global_series.append((info, self._infer_dtype(initializer)))
                continue
            if item.kind == "VarDeclaration":
                initializer = item.child("initializer")
                if initializer is not None and self._is_input_call(initializer):
                    info = self.ctx.declare_var(
                        item.field("name"),
                        type_ref=self._type_ref_name(item),
                        qualifier="input",
                        declaration_kind="input",
                        is_series=True,
                        is_mutable=False,
                        loc=item.loc,
                    )
                    meta = self._build_input_metadata(item, initializer, info.py_name)
                    self.input_series.append((info, meta["type"], meta))
                    self.ctx.input_metadata.append(meta["public"])
                else:
                    info = self.ctx.declare_var(
                        item.field("name"),
                        type_ref=self._type_ref_name(item),
                        qualifier=item.field("explicit_qualifier"),
                        declaration_kind=str(item.field("mode") or "normal"),
                        is_series=True,
                        is_mutable=True,
                        loc=item.loc,
                    )
                    self.global_series.append((info, self._infer_dtype(initializer)))

    def _emit_statement(self, node: ASTNode) -> None:
        self.ctx.coverage.generated()
        self.emitter.source_comment(node.loc, node.source)
        if node.kind == "VarDeclaration":
            self._emit_var_declaration(node)
            return
        if node.kind == "TupleDeclaration":
            self._emit_tuple_declaration(node)
            return
        if node.kind == "Reassignment":
            self._emit_reassignment(node)
            return
        if node.kind == "ExpressionStatement":
            expression = node.child("expression")
            if expression is None:
                raise UnsupportedNodeError("ExpressionStatement without expression")
            self.emitter.line(self.translate_expression(expression), loc=node.loc, source=node.source)
            return
        if node.kind == "IfStructure":
            self._emit_if(node)
            return
        if node.kind == "ForRangeStructure":
            self._emit_for_range(node)
            return
        if node.kind == "Block":
            for statement in node.children("statements"):
                self._emit_statement(statement)
            return
        raise UnsupportedNodeError(f"Unsupported statement node: {node.kind}")

    def _resolve_or_declare_var(
        self,
        node: ASTNode,
        name: str,
        initializer: ASTNode | None = None,
    ) -> VariableInfo:
        try:
            return self.ctx.resolve_var(name)
        except ScopeResolutionError:
            is_global = self.ctx.current_scope.kind == "global"
            info = self.ctx.declare_var(
                name,
                type_ref=self._type_ref_name(node),
                qualifier=node.field("explicit_qualifier"),
                declaration_kind=str(node.field("mode") or "normal"),
                is_series=is_global,
                is_mutable=True,
                loc=node.loc,
            )
            if is_global:
                self.global_series.append((info, self._infer_dtype(initializer)))
            return info

    def _emit_var_declaration(self, node: ASTNode) -> None:
        name = str(node.field("name"))
        initializer = node.child("initializer")
        if initializer is None:
            raise UnsupportedNodeError(f"VarDeclaration {name} missing initializer")
        if self._is_input_call(initializer):
            return
        info = self._resolve_or_declare_var(node, name, initializer)
        if self.ctx.current_scope.kind == "global":
            expr = self.translate_expression(initializer)
            if info.declaration_kind == "var":
                self.emitter.line(f'if not self._var_initialized["{info.py_name}"]:', loc=node.loc, source=node.source)
                self.emitter.indent()
                self.emitter.line(f"self.{info.py_name}.set_current({expr})")
                self.emitter.line(f'self._var_initialized["{info.py_name}"] = True')
                self.emitter.dedent()
            else:
                self.emitter.line(f"self.{info.py_name}.set_current({expr})", loc=node.loc, source=node.source)
            return
        expr = self.translate_expression(initializer)
        self.emitter.line(f"{info.py_name} = {expr}", loc=node.loc, source=node.source)

    def _tuple_targets(self, node: ASTNode) -> list[str]:
        raw_targets = node.raw.get("targets") or node.raw.get("names") or node.raw.get("elements") or []
        targets: list[str] = []
        if not isinstance(raw_targets, list):
            raise UnsupportedNodeError("TupleDeclaration targets must be a list")
        for item in raw_targets:
            if isinstance(item, str):
                targets.append(item)
            elif isinstance(item, dict):
                target = ASTNode(item)
                if target.kind == "Identifier":
                    targets.append(str(target.field("name")))
                elif target.kind in {"Discard", "TupleDiscard"}:
                    targets.append("_")
                else:
                    raise UnsupportedNodeError(f"Unsupported tuple target: {target.kind}")
        return targets

    def _emit_tuple_declaration(self, node: ASTNode) -> None:
        initializer = node.child("initializer") or node.child("value")
        if initializer is None:
            raise UnsupportedNodeError("TupleDeclaration missing initializer")
        targets = self._tuple_targets(node)
        if not targets:
            raise UnsupportedNodeError("TupleDeclaration has no targets")
        temp_names: list[str] = []
        assignments: list[tuple[VariableInfo | None, str]] = []
        for index, name in enumerate(targets, start=1):
            if name == "_":
                temp_names.append(f"_discard_{index}")
                assignments.append((None, temp_names[-1]))
                continue
            info = self._resolve_or_declare_var(node, name, initializer)
            temp = f"_{info.py_name}"
            temp_names.append(temp)
            assignments.append((info, temp))
        self.emitter.line(
            f"{', '.join(temp_names)} = {self.translate_expression(initializer)}",
            loc=node.loc,
            source=node.source,
        )
        for target_info, temp in assignments:
            if target_info is None:
                continue
            if target_info.is_series:
                self.emitter.line(f"self.{target_info.py_name}.set_current({temp})")
            else:
                self.emitter.line(f"{target_info.py_name} = {temp}")

    def _emit_reassignment(self, node: ASTNode) -> None:
        target = node.child("target")
        value = node.child("value")
        if target is None or value is None:
            raise UnsupportedNodeError("Reassignment missing target/value")
        if target.kind != "Identifier":
            raise UnsupportedNodeError(f"Unsupported reassignment target: {target.kind}")
        info = self.ctx.resolve_var(target.field("name"))
        rhs = self.translate_expression(value)
        if info.is_series:
            if node.field("op") in {":=", "="}:
                self.emitter.line(f"self.{info.py_name}.set_current({rhs})", loc=node.loc, source=node.source)
            else:
                operator = str(node.field("op")).replace("=", "")
                self.emitter.line(
                    f"self.{info.py_name}.set_current(self.{info.py_name}.current {operator} ({rhs}))",
                    loc=node.loc,
                    source=node.source,
                )
            return
        if node.field("op") in {":=", "="}:
            self.emitter.line(f"{info.py_name} = {rhs}", loc=node.loc, source=node.source)
        else:
            operator = str(node.field("op")).replace("=", "")
            self.emitter.line(f"{info.py_name} = {info.py_name} {operator} ({rhs})", loc=node.loc, source=node.source)

    def _emit_if(self, node: ASTNode) -> None:
        condition = node.child("condition")
        then_block = node.child("then_block")
        else_block = node.child("else_block")
        if condition is None or then_block is None:
            raise UnsupportedNodeError("IfStructure missing condition or then_block")
        self.emitter.line(f"if pine_bool({self.translate_expression(condition)}):", loc=node.loc, source=node.source)
        self.emitter.indent()
        self.ctx.enter_scope("block")
        if then_block.children("statements"):
            for statement in then_block.children("statements"):
                self._emit_statement(statement)
        else:
            self.emitter.line("pass")
        self.ctx.exit_scope()
        self.emitter.dedent()
        for branch in node.children("else_if_branches"):
            branch_condition = branch.child("condition")
            branch_block = branch.child("block") or branch.child("then_block")
            if branch_condition is None or branch_block is None:
                raise UnsupportedNodeError("Else-if branch missing condition or block")
            self.emitter.line(f"elif pine_bool({self.translate_expression(branch_condition)}):")
            self.emitter.indent()
            self.ctx.enter_scope("block")
            for statement in branch_block.children("statements"):
                self._emit_statement(statement)
            self.ctx.exit_scope()
            self.emitter.dedent()
        if else_block is not None:
            self.emitter.line("else:")
            self.emitter.indent()
            self.ctx.enter_scope("block")
            if else_block.children("statements"):
                for statement in else_block.children("statements"):
                    self._emit_statement(statement)
            else:
                self.emitter.line("pass")
            self.ctx.exit_scope()
            self.emitter.dedent()

    def _emit_for_range(self, node: ASTNode) -> None:
        self.ctx.imports.require_from("pinelib.core", "pine_range")
        variable = str(node.field("variable"))
        self.ctx.enter_scope("loop")
        loop_info = self.ctx.declare_var(
            variable,
            type_ref="int",
            qualifier=None,
            declaration_kind="loop",
            is_series=False,
            is_mutable=True,
            loc=node.loc,
            prefer_py_name=variable,
        )
        loop_name = loop_info.py_name
        start_node = node.child("start")
        end_node = node.child("end")
        if start_node is None or end_node is None:
            raise UnsupportedNodeError("ForRangeStructure requires start and end expressions")
        start = self.translate_expression(start_node)
        end = self.translate_expression(end_node)
        step_node = node.child("step")
        if step_node is not None:
            step = self.translate_expression(step_node)
            self.emitter.line(f"for {loop_name} in pine_range({start}, {end}, {step}):", loc=node.loc, source=node.source)
        else:
            self.emitter.line(f"for {loop_name} in pine_range({start}, {end}):", loc=node.loc, source=node.source)
        self.emitter.indent()
        body = node.child("body")
        if body is None or not body.children("statements"):
            self.emitter.line("pass")
        else:
            for statement in body.children("statements"):
                self._emit_statement(statement)
        self.emitter.dedent()
        self.ctx.exit_scope()

    def translate_expression(self, node: ASTNode, *, runtime_expr: str = "self.rt") -> str:
        self.ctx.coverage.generated()
        if node.kind == "Literal":
            return repr(literal_value(node))
        if node.kind == "Identifier":
            return self._translate_identifier(node, runtime_expr=runtime_expr)
        if node.kind == "MemberAccessExpr":
            return self._translate_member_access(node, runtime_expr=runtime_expr)
        if node.kind == "BinaryExpr":
            left_node = node.child("left")
            right_node = node.child("right")
            if left_node is None or right_node is None:
                raise UnsupportedNodeError("BinaryExpr requires left and right operands")
            left = self.translate_expression(left_node, runtime_expr=runtime_expr)
            right = self.translate_expression(right_node, runtime_expr=runtime_expr)
            op = node.field("op")
            return f"({left} {op} {right})"
        if node.kind == "UnaryExpr":
            operand_node = node.child("operand")
            if operand_node is None:
                raise UnsupportedNodeError("UnaryExpr requires an operand")
            operand = self.translate_expression(operand_node, runtime_expr=runtime_expr)
            return f"({node.field('op')}{operand})"
        if node.kind in {"HistoryRefExpr", "HistoryReference", "SubscriptExpr", "IndexExpr"}:
            return self._translate_history_reference(node, runtime_expr=runtime_expr)
        if node.kind == "ConditionalExpr":
            condition_node = node.child("condition")
            true_node = node.child("then")
            false_node = node.child("else")
            if condition_node is None or true_node is None or false_node is None:
                raise UnsupportedNodeError("ConditionalExpr requires condition/then/else")
            condition = self.translate_expression(condition_node, runtime_expr=runtime_expr)
            when_true = self.translate_expression(true_node, runtime_expr=runtime_expr)
            when_false = self.translate_expression(false_node, runtime_expr=runtime_expr)
            return f"({when_true} if pine_bool({condition}) else {when_false})"
        if node.kind == "IfStructure":
            return self._translate_if_expression(node, runtime_expr=runtime_expr)
        if node.kind == "CallExpr":
            return self._translate_call(node, runtime_expr=runtime_expr)
        raise UnsupportedNodeError(f"Unsupported expression node: {node.kind}")

    def _translate_identifier(self, node: ASTNode, *, runtime_expr: str) -> str:
        name = str(node.field("name"))
        if name in BUILTIN_SERIES:
            return f"{runtime_expr}.{name}"
        if name == "bar_index":
            return f"{runtime_expr}.bar_index"
        if name == "na":
            return "na"
        if name == "hl2":
            return f"(({runtime_expr}.high + {runtime_expr}.low) / 2)"
        if name == "hlc3":
            return f"(({runtime_expr}.high + {runtime_expr}.low + {runtime_expr}.close) / 3)"
        if name == "ohlc4":
            return f"(({runtime_expr}.open + {runtime_expr}.high + {runtime_expr}.low + {runtime_expr}.close) / 4)"
        if name == "hlcc4":
            return f"(({runtime_expr}.high + {runtime_expr}.low + {runtime_expr}.close + {runtime_expr}.close) / 4)"
        info = self.ctx.resolve_var(name)
        if info.is_series:
            return f"self.{info.py_name}.current"
        return info.py_name

    def _translate_member_access(self, node: ASTNode, *, runtime_expr: str) -> str:
        chain = member_chain(node)
        if chain is None:
            raise UnsupportedNodeError("Invalid MemberAccessExpr")
        if chain.startswith("syminfo."):
            return f"{runtime_expr}.syminfo.{chain.split('.', 1)[1]}"
        if chain.startswith("timeframe."):
            return f"{runtime_expr}.timeframe.{chain.split('.', 1)[1]}"
        if chain.startswith("barstate."):
            return f"{runtime_expr}.barstate.{chain.split('.', 1)[1]}"
        if chain == "strategy.long":
            return '"long"'
        if chain == "strategy.short":
            return '"short"'
        if chain.startswith("strategy.commission."):
            return repr(chain.rsplit(".", 1)[-1])
        if chain.startswith("strategy.oca."):
            return repr(chain.rsplit(".", 1)[-1])
        if chain.startswith("barmerge."):
            return repr(chain)
        if chain.startswith("color."):
            self.ctx.imports.require_from("pinelib.colors", "color", alias="pine_color")
            return f"pine_color.{chain.split('.', 1)[1]}"
        if chain.startswith("array."):
            return f"{runtime_expr}.array.{chain.split('.', 1)[1]}"
        if chain.startswith("request."):
            return f"{runtime_expr}.request.{chain.split('.', 1)[1]}"
        if chain.startswith("math.") or chain.startswith("ta.") or chain.startswith("str."):
            return chain
        if chain.startswith(("line.", "label.", "box.", "table.")):
            self.ctx.add_diagnostic(
                VISUAL_OBJECT_USED_AS_VALUE,
                "visual object id used as a value is not supported",
                Severity.ERROR,
                location=node.loc,
            )
            raise TypeResolutionError("Visual object member access cannot be used as a value")
        return chain

    def _translate_history_reference(self, node: ASTNode, *, runtime_expr: str) -> str:
        base = node.child("base") or node.child("object") or node.child("target") or node.child("expression")
        offset_node = node.child("offset") or node.child("index")
        if base is None or offset_node is None:
            raise UnsupportedNodeError("History reference requires base and offset")
        if base.kind == "Literal":
            raise TypeResolutionError("History reference on literal is invalid")
        offset = self.translate_expression(offset_node, runtime_expr=runtime_expr)
        if base.kind == "Identifier":
            name = str(base.field("name"))
            if name in BUILTIN_SERIES:
                return f"{runtime_expr}.{name}[{offset}]"
            info = self.ctx.resolve_var(name)
            if info.is_series:
                return f"self.{info.py_name}[{offset}]"
        rendered = self.translate_expression(base, runtime_expr=runtime_expr)
        return f"{runtime_expr}.history({rendered}, {offset})"

    def _translate_if_expression(self, node: ASTNode, *, runtime_expr: str) -> str:
        condition = node.child("condition")
        then_expr = self._block_expression(node.child("then_block"), runtime_expr=runtime_expr)
        else_expr = self._block_expression(node.child("else_block"), runtime_expr=runtime_expr)
        if condition is None or then_expr is None or else_expr is None:
            raise UnsupportedNodeError("IfStructure expression form requires expression-only branches")
        return f"({then_expr} if pine_bool({self.translate_expression(condition, runtime_expr=runtime_expr)}) else {else_expr})"

    def _block_expression(self, block: ASTNode | None, *, runtime_expr: str) -> str | None:
        if block is None:
            return None
        statements = block.children("statements")
        if len(statements) != 1 or statements[0].kind != "ExpressionStatement":
            return None
        expression = statements[0].child("expression")
        if expression is None:
            return None
        return self.translate_expression(expression, runtime_expr=runtime_expr)

    def _translate_call(self, node: ASTNode, *, runtime_expr: str) -> str:
        callee = node.child("callee")
        if callee is None:
            raise UnsupportedNodeError("CallExpr missing callee")
        callee_chain = member_chain(callee)
        if callee_chain is None and callee.kind == "Identifier":
            callee_chain = str(callee.field("name"))
        if callee_chain is None:
            raise UnsupportedBuiltinError("Unsupported call target")
        if callee_chain == "request.security":
            return self._translate_request_security(node, runtime_expr=runtime_expr)
        if callee_chain in {"time", "time_close"}:
            return self._translate_time_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain.startswith("strategy.") and callee_chain not in {"strategy.long", "strategy.short"}:
            return self._translate_strategy_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain in {
            "input.int",
            "input.float",
            "input.bool",
            "input.string",
            "input.timeframe",
            "input.session",
            "input.source",
        }:
            return self._translate_input_runtime_lookup(node)
        if callee_chain.startswith("ta."):
            return self._translate_ta_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain.startswith("math."):
            return self._translate_math_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain.startswith("str."):
            return self._translate_str_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain in {"plot", "plotshape", "plotchar", "hline", "fill", "bgcolor", "barcolor"}:
            return self._translate_visual_call(callee_chain, node, runtime_expr=runtime_expr)
        self.ctx.add_diagnostic(
            UNKNOWN_OVERLOAD,
            f"unknown or unsupported call overload: {callee_chain}",
            Severity.ERROR if self.strict else Severity.WARNING,
            location=node.loc,
        )
        raise UnsupportedBuiltinError(callee_chain)

    def _translate_request_security(self, node: ASTNode, *, runtime_expr: str) -> str:
        arguments = self._call_arguments(node)
        if len(arguments) < 3:
            raise UnsupportedBuiltinError("request.security requires at least 3 arguments")
        expression = arguments[2][1]
        if self._contains_request_call(expression):
            severity = Severity.ERROR if self.strict else Severity.WARNING
            self.ctx.add_diagnostic(
                WARNING_NESTED_SECURITY,
                "request.security inside request.security expression may not be supported by PineLib MVP",
                severity,
                location=expression.loc,
            )
            if self.strict:
                raise UnsupportedBuiltinError("nested request.security is unsupported in strict mode")
        state_id = state_id_for_call(self.ctx, node, "security")
        call_args = [
            self.translate_expression(arguments[0][1], runtime_expr=runtime_expr),
            self.translate_expression(arguments[1][1], runtime_expr=runtime_expr),
            f"lambda request_rt: {self.translate_expression(expression, runtime_expr='request_rt')}",
        ]
        kwargs: list[str] = []
        for name, arg in arguments[3:]:
            if name is None:
                continue
            kwargs.append(f"{name}={self.translate_expression(arg, runtime_expr=runtime_expr)}")
        kwargs.extend(
            [
                f"runtime={runtime_expr}",
                f'state_id="{state_id}"',
                f'source_map="{node.loc.source_map if node.loc else ""}"',
            ]
        )
        self.ctx.coverage.builtin("request.security")
        return f"{runtime_expr}.request.security({', '.join(call_args + kwargs)})"

    def _translate_time_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        arguments = self._call_arguments(node)
        func_name = "time" if name == "time" else "time_close"
        args = [self.translate_expression(arg, runtime_expr=runtime_expr) for _, arg in arguments]
        args.extend([f"runtime={runtime_expr}", f'source_map="{node.loc.source_map if node.loc else ""}"'])
        self.ctx.coverage.builtin(name)
        return f"{runtime_expr}.timefunc.{func_name}({', '.join(args)})"

    def _translate_strategy_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        method = name.split(".", 1)[1]
        arguments = self._call_arguments(node)
        pieces = []
        for arg_name, arg in arguments:
            rendered = self.translate_expression(arg, runtime_expr=runtime_expr)
            if arg_name is None:
                pieces.append(rendered)
            else:
                pieces.append(f"{arg_name}={rendered}")
        pieces.append(f'source_map="{node.loc.source_map if node.loc else ""}"')
        self.ctx.coverage.builtin(name)
        return f"self.ctx.{method}({', '.join(pieces)})"

    def _translate_visual_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        arguments = self._call_arguments(node)
        pieces = []
        for arg_name, arg in arguments:
            rendered = self.translate_expression(arg, runtime_expr=runtime_expr)
            if arg_name is None:
                pieces.append(rendered)
            else:
                pieces.append(f"{arg_name}={rendered}")
        pieces.append(f'source_map="{node.loc.source_map if node.loc else ""}"')
        self.ctx.coverage.builtin(name)
        return f"{runtime_expr}.visual.{name}({', '.join(pieces)})"

    def _translate_input_runtime_lookup(self, node: ASTNode) -> str:
        arguments = self._call_arguments(node)
        if not arguments:
            raise UnsupportedBuiltinError("input.* requires a default value")
        return repr(literal_value(arguments[0][1]))

    def _translate_ta_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        function_name = name.split(".", 1)[1]
        import_name = self.ctx.imports.require_from("pinelib.ta", function_name)
        arguments = [self.translate_expression(arg, runtime_expr=runtime_expr) for _, arg in self._call_arguments(node)]
        if function_name in STATEFUL_TA_FUNCTIONS:
            state_id = state_id_for_call(self.ctx, node, function_name)
            arguments.extend([f"runtime={runtime_expr}", f'state_id="{state_id}"'])
        self.ctx.coverage.builtin(name)
        return f"{import_name}({', '.join(arguments)})"

    def _translate_math_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        function_name = name.split(".", 1)[1]
        import_name = self.ctx.imports.require_from("pinelib.math", function_name)
        arguments = [self.translate_expression(arg, runtime_expr=runtime_expr) for _, arg in self._call_arguments(node)]
        self.ctx.coverage.builtin(name)
        return f"{import_name}({', '.join(arguments)})"

    def _translate_str_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        self.ctx.imports.require_from("pinelib.strings", "str")
        function_name = name.split(".", 1)[1]
        arguments = [self.translate_expression(arg, runtime_expr=runtime_expr) for _, arg in self._call_arguments(node)]
        self.ctx.coverage.builtin(name)
        return f"pine_str.{function_name}({', '.join(arguments)})"

    def _call_arguments(self, node: ASTNode) -> list[tuple[str | None, ASTNode]]:
        result: list[tuple[str | None, ASTNode]] = []
        for argument in node.children("arguments", "args"):
            value = argument.child("value") or argument.child("expression")
            if value is None:
                raise UnsupportedNodeError("Argument missing value")
            result.append((argument.field("name"), value))
        return result

    def _extract_declaration_title(self, declaration: ASTNode) -> str:
        call = declaration.child("call")
        if call is None:
            return "Generated"
        arguments = self._call_arguments(call)
        if arguments and arguments[0][0] is None and arguments[0][1].kind == "Literal":
            return str(literal_value(arguments[0][1]))
        return "Generated"

    def _strategy_context_kwargs(self, declaration: ASTNode) -> list[tuple[str, str]]:
        call = declaration.child("call")
        if call is None:
            return []
        kwargs: list[tuple[str, str]] = []
        metadata: dict[str, Any] = {}
        for name, value_node in self._call_arguments(call):
            rendered = self.translate_expression(value_node)
            key = name or ("title" if not metadata else f"arg_{len(metadata)}")
            metadata[key] = self._literal_or_rendered(value_node, rendered)
            if name in STRATEGY_CONTEXT_FIELDS:
                kwargs.append((name, rendered))
            elif name is not None and name not in {"overlay"}:
                self.ctx.add_diagnostic(
                    UNSUPPORTED_DECLARATION_ARG,
                    f"declaration argument {name!r} is not mapped to StrategyContext",
                    Severity.ERROR if self.strict else Severity.WARNING,
                    location=value_node.loc,
                )
                self.ctx.unsupported_declaration_args.append(name)
                if self.strict:
                    raise UnsupportedBuiltinError(name)
        self.ctx.strategy_metadata = metadata
        return kwargs

    def _literal_or_rendered(self, node: ASTNode, rendered: str) -> Any:
        if node.kind == "Literal":
            return literal_value(node)
        if node.kind == "MemberAccessExpr":
            try:
                return pyast.literal_eval(rendered)
            except (ValueError, SyntaxError):
                return rendered
        return rendered

    def _contains_request_call(self, node: ASTNode) -> bool:
        for descendant in node.descendants():
            if descendant.kind == "CallExpr":
                callee = descendant.child("callee")
                if callee is not None and member_chain(callee) == "request.security":
                    return True
        return False

    def _is_input_call(self, node: ASTNode) -> bool:
        callee = node.child("callee")
        return node.kind == "CallExpr" and callee is not None and member_chain(callee) in {
            "input.int",
            "input.float",
            "input.bool",
            "input.string",
            "input.timeframe",
            "input.session",
            "input.source",
        }

    def _build_input_metadata(self, declaration: ASTNode, initializer: ASTNode, py_name: str) -> dict[str, Any]:
        callee = initializer.child("callee")
        chain = None if callee is None else member_chain(callee)
        if chain is None:
            raise UnsupportedBuiltinError("input declaration is missing a valid callee")
        info_type = chain.split(".", 1)[1]
        args = self._call_arguments(initializer)
        default_node = args[0][1]
        default_value = literal_value(default_node)
        metadata = {
            "pine_name": declaration.field("name"),
            "py_name": py_name,
            "type": {"timeframe": "string", "session": "string"}.get(info_type, info_type),
            "qualifier": "input",
            "default": default_value,
            "title": None,
            "minval": None,
            "maxval": None,
            "step": None,
            "options": None,
            "group": None,
            "inline": None,
            "tooltip": None,
            "confirm": False,
            "display": "all",
            "active": True,
            "source_map": declaration.loc.source_map if declaration.loc else None,
        }
        positional_meta = ["title"]
        for index, (name, value) in enumerate(args[1:]):
            key = name or (positional_meta[index] if index < len(positional_meta) else None)
            if key in {
                "title",
                "minval",
                "maxval",
                "step",
                "options",
                "group",
                "inline",
                "tooltip",
                "confirm",
                "display",
                "active",
            }:
                metadata[key] = self._literal_or_rendered(value, self.translate_expression(value))
        public_meta = dict(metadata)
        return {
            "type": metadata["type"],
            "default_python": repr(default_value),
            "public": public_meta,
        }

    def _infer_dtype(self, node: ASTNode | None) -> str:
        if node is None:
            return "object"
        if node.kind == "Literal":
            literal_type = node.field("literal_type")
            return "float" if literal_type == "float" else str(literal_type or "object")
        if self._is_input_call(node):
            callee = node.child("callee")
            chain = None if callee is None else member_chain(callee)
            if chain is None:
                return "object"
            info_type = chain.split(".", 1)[1]
            return {"timeframe": "string", "session": "string"}.get(info_type, info_type)
        if node.kind == "BinaryExpr":
            return "float"
        return "object"

    def _type_ref_name(self, node: ASTNode) -> str | None:
        type_ref = node.child("type_ref")
        if type_ref is None:
            return None
        name = type_ref.field("name")
        return str(name) if name is not None else None

    def _build_metadata(self, program: ASTProgram, *, title: str, module_name: str) -> dict[str, Any]:
        declaration = {
            "kind": self.ctx.mode,
            "title": title,
            "arguments": self.ctx.strategy_metadata if self.ctx.mode == "strategy" else {},
        }
        return {
            "ast2python_version": __version__,
            "generator_milestone": "v0.2.0",
            "target_runtime_contract": RUNTIME_CONTRACT_VERSION,
            "pine_version": program.field("version", "language_version", default=6),
            "source_file": f"{module_name}.pine",
            "declaration": declaration,
            "inputs": self.ctx.input_metadata,
            "used_builtins": sorted(self.ctx.coverage.builtins),
            "unsupported_nodes": [],
            "unsupported_declaration_args": sorted(set(self.ctx.unsupported_declaration_args)),
            "diagnostics": [item.to_dict() for item in self.ctx.diagnostics],
            "source_map_file": f"{module_name}.sourcemap.json",
        }


def translate_ast(
    program: ASTProgram | dict[str, Any],
    *,
    strict: bool = False,
    emit_source_comments: bool = True,
    module_name: str | None = None,
) -> TranslationResult:
    return Translator(strict=strict, emit_source_comments=emit_source_comments).translate_program(
        program,
        module_name=module_name,
    )
