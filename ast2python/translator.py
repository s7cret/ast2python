from __future__ import annotations

import ast as pyast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from ast2python.ast.schema import ASTNode, ASTProgram, ensure_program_node, load_ast, validate_ast
from ast2python.binder import BUILTIN_SIGNATURES, bind_builtin_call
from ast2python.context import TranslationContext, VariableInfo
from ast2python.diagnostics import (
    BINDER_SIGNATURE_MISMATCH,
    BINDER_UNSUPPORTED_BUILTIN,
    BOOL_NA_OVERLOAD,
    CALC_ON_EVERY_TICK_UNSAFE,
    CONTRACT_VERSION_MISMATCH,
    EXTERNAL_LIBRARY_CALL,
    NESTED_REQUEST_SECURITY,
    REFERENCE_COPY_POLICY,
    REFERENCE_HISTORY_UNSUPPORTED,
    REQUEST_SECURITY_CAPTURE_UNSAFE,
    UNKNOWN_OVERLOAD,
    UNSUPPORTED_DECLARATION_ARG,
    UNSUPPORTED_NODE,
    UNSUPPORTED_REQUEST,
    VARIP_UNSAFE,
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
from ast2python.naming import snake_case
from ast2python.state import state_id_for_call
from ast2python.templates.module import base_class_for_mode, class_name_for_mode
from ast2python.types import TypeInfo, join_qualifiers, make_type_info
from ast2python.unsupported import node_kind_counts, unsupported_node_catalog
from ast2python.version import RUNTIME_CONTRACT_VERSION, __version__

STATEFUL_TA_FUNCTIONS = {"sma", "ema", "rma", "atr", "rsi", "macd", "dmi", "supertrend", "stoch", "adx", "vwma", "hma", "vwap", "roc", "mom", "sar", "obv", "stdev", "variance", "cci", "mfi", "cum", "range", "tsi", "cmo", "tr"}
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
DERIVED_BUILTIN_SERIES = {"hl2", "hlc3", "ohlc4", "hlcc4"}
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
REFERENCE_TYPES = {"array", "map", "matrix", "PineArray", "PineMap", "PineMatrix"}
INPUT_CALLS = {
    "input.int",
    "input.float",
    "input.bool",
    "input.string",
    "input.timeframe",
    "input.session",
    "input.source",
    "input.time",
}
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


def member_chain(node: ASTNode) -> str | None:
    if node.kind == "Identifier":
        name = node.field("name")
        return name if isinstance(name, str) else None
    if node.kind == "GenericInstantiationExpr":
        base = node.child("base")
        return None if base is None else member_chain(base)
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
        meta_path.write_text(
            json.dumps(self.metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        sourcemap_path.write_text(
            json.dumps(self.source_map, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        coverage_path.write_text(
            json.dumps(self.coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return {
            "python": py_path,
            "metadata": meta_path,
            "source_map": sourcemap_path,
            "coverage": coverage_path,
        }


class Translator:
    def __init__(
        self,
        *,
        strict: bool = False,
        emit_source_comments: bool = True,
        allow_invalid_ast: bool = False,
        allow_contract_mismatch: bool = False,
        allow_external_library_stubs: bool = False,
        allow_unsupported_request_stubs: bool = False,
        allow_realtime_local_simulation: bool = False,
    ) -> None:
        self.strict = strict
        self.emit_source_comments = emit_source_comments
        self.allow_invalid_ast = allow_invalid_ast
        self.allow_contract_mismatch = allow_contract_mismatch
        self.allow_external_library_stubs = allow_external_library_stubs
        self.allow_unsupported_request_stubs = allow_unsupported_request_stubs
        self.allow_realtime_local_simulation = allow_realtime_local_simulation
        self.parity_safe = True
        self.unsupported_features: set[str] = set()
        self.parity_risks: list[str] = []
        self.ctx = TranslationContext(strict=strict)
        self.emitter = CodeEmitter(self.ctx.source_map, emit_source_comments=emit_source_comments)
        self.global_series: list[tuple[VariableInfo, str]] = []
        self.input_series: list[tuple[VariableInfo, str, dict[str, Any]]] = []
        self.var_flags: list[VariableInfo] = []
        self.functions: set[str] = set()
        self.methods: set[str] = set()
        self._temp_series_index: int = 0

    def translate_file(
        self, path: str | Path, *, module_name: str | None = None
    ) -> TranslationResult:
        return self.translate_program(load_ast(path), module_name=module_name or Path(path).stem)

    def translate_program(
        self, program: ASTProgram | dict[str, Any], *, module_name: str | None = None
    ) -> TranslationResult:
        if isinstance(program, dict):
            program = ensure_program_node(program)
        problems = validate_ast(program)
        if problems:
            raise ValidationError("; ".join(problems))
        self._enforce_frontend_contract(program)
        for _ in program.descendants():
            self.ctx.coverage.seen()
        declaration = program.declaration
        if declaration is None:
            raise ValidationError("Program declaration is required")
        mode = declaration.field("script_type", default="indicator")
        self.ctx.mode = str(mode)
        title = self._extract_declaration_title(declaration)
        self._enforce_realtime_boundary(declaration)
        self._enforce_varip_boundary(program)
        if self.ctx.mode != "strategy":
            self._collect_declaration_metadata(declaration)
        result_module_name = module_name or self.ctx.naming.reserve(title or "generated")
        self._emit_module(program, declaration, title=title, module_name=result_module_name)
        metadata = self._build_metadata(program, title=title, module_name=result_module_name)
        coverage = self.ctx.coverage.to_dict()
        coverage.update(self._source_map_line_coverage(program))
        return TranslationResult(
            code=self.emitter.render(),
            metadata=metadata,
            source_map=self.ctx.source_map.to_list(),
            coverage=coverage,
            diagnostics=self.ctx.diagnostics,
            module_name=result_module_name,
        )

    def _source_map_line_coverage(self, program: ASTProgram) -> dict[str, Any]:
        executable_kinds = {
            "VarDeclaration",
            "TupleDeclaration",
            "Reassignment",
            "ExpressionStatement",
            "IfStructure",
            "SwitchStructure",
            "SwitchStatement",
            "ForRangeStructure",
            "ForStructure",
            "WhileStructure",
            "WhileStatement",
            "BreakStatement",
            "ContinueStatement",
            "FunctionDeclaration",
            "FunctionDecl",
            "FunctionDefinition",
            "MethodDeclaration",
            "MethodDecl",
            "TypeDeclaration",
            "UserTypeDeclaration",
            "UDTDeclaration",
            "EnumDeclaration",
            "EnumDecl",
        }
        executable_lines: set[int] = set()
        for node in program.descendants():
            if node.kind not in executable_kinds or node.loc is None or node.loc.line is None:
                continue
            if node.kind == "VarDeclaration" and self._is_input_call(
                node.child("initializer") or ASTNode({})
            ):
                continue
            executable_lines.add(node.loc.line)
        mapped_lines = {
            entry.pine_line for entry in self.ctx.source_map.entries if entry.pine_line is not None
        }
        covered = executable_lines & mapped_lines
        ratio = 1.0 if not executable_lines else len(covered) / len(executable_lines)
        return {
            "executable_pine_lines": len(executable_lines),
            "source_mapped_executable_lines": len(covered),
            "source_map_executable_line_ratio": ratio,
        }

    def _enforce_frontend_contract(self, program: ASTProgram) -> None:
        frontend_diagnostics = [
            item
            for item in program.field("diagnostics", default=[]) or []
            if isinstance(item, dict)
            and str(item.get("severity", "")).lower() in {"error", "fatal"}
        ]
        if frontend_diagnostics:
            self.ctx.add_diagnostic(
                "P2A_FRONTEND_DIAGNOSTIC_BLOCK",
                "Pine2AST embedded ERROR/FATAL diagnostics block code generation",
                Severity.ERROR,
                details={"frontend_diagnostics": frontend_diagnostics},
            )
            if not self.allow_invalid_ast:
                raise ValidationError("Pine2AST ERROR/FATAL diagnostics block code generation")
            self.parity_safe = False
            self.parity_risks.append("allow_invalid_ast override used with frontend errors")

        metadata = program.field("producer_metadata")
        runtime_contract = None
        contract = None
        if isinstance(metadata, dict):
            contract = metadata.get("contract")
            runtime_contract = metadata.get("runtime_contract") or metadata.get(
                "runtime_contract_profile"
            )
        expected = RUNTIME_CONTRACT_VERSION
        aliases = {expected, "v1.4", "runtime_contract_v1_4", "runtime_contract_v1.4"}
        metadata_contract_ok = (
            isinstance(metadata, dict)
            and contract == "pain.ast_contract.v1"
            and runtime_contract in aliases
        )
        if not metadata_contract_ok:
            self.ctx.add_diagnostic(
                CONTRACT_VERSION_MISMATCH,
                "Pine2AST producer metadata missing or mismatched contract/runtime profile",
                Severity.ERROR,
                details={
                    "expected_contract": "pain.ast_contract.v1",
                    "actual_contract": contract,
                    "expected_runtime_contract": expected,
                    "actual_runtime_contract": runtime_contract,
                    "metadata": metadata,
                },
            )
            if not self.allow_contract_mismatch:
                raise ValidationError("Pine2AST producer metadata missing/mismatched runtime contract")
            self.parity_safe = False
            self.parity_risks.append("allow_contract_mismatch override used")

        if metadata_contract_ok:
            unsafe_gates = {
                key: metadata.get(key)
                for key in ("parser_gate", "semantic_gate")
                if metadata.get(key) != "pass"
            }
            if unsafe_gates:
                self.ctx.add_diagnostic(
                    "P2A_FRONTEND_GATE_BLOCK",
                    "Pine2AST producer metadata gate status is not pass",
                    Severity.ERROR,
                    details={"gates": unsafe_gates},
                )
                if not self.allow_invalid_ast:
                    raise ValidationError("Pine2AST producer metadata gates are not pass")
                self.parity_safe = False
                self.parity_risks.append("allow_invalid_ast override used with non-pass frontend gates")

    def _enforce_realtime_boundary(self, declaration: ASTNode) -> None:
        if self.ctx.mode != "strategy" or not self._strategy_calc_on_every_tick_enabled(declaration):
            return
        self.ctx.add_diagnostic(
            CALC_ON_EVERY_TICK_UNSAFE,
            "calc_on_every_tick requires TradingView realtime rollback/varip semantics and is rejected in parity codegen mode",
            Severity.ERROR,
            details={"allow_flag": "allow_realtime_local_simulation"},
        )
        if not self.allow_realtime_local_simulation:
            raise ValidationError("calc_on_every_tick is unsupported in parity codegen mode")
        self.parity_safe = False
        self.unsupported_features.add("realtime_local_simulation")
        self.parity_risks.append(
            "allow_realtime_local_simulation override used; supplied tick mode is local simulation only"
        )

    def _enforce_varip_boundary(self, program: ASTProgram) -> None:
        varip_nodes = [
            node
            for node in program.descendants()
            if node.kind == "VarDeclaration" and str(node.field("mode", default="")).lower() == "varip"
        ]
        if not varip_nodes:
            return
        self.ctx.add_diagnostic(
            VARIP_UNSAFE,
            "varip requires TradingView realtime rollback semantics and is rejected in parity codegen mode",
            Severity.ERROR,
            details={"allow_flag": "allow_realtime_local_simulation", "count": len(varip_nodes)},
        )
        if not self.allow_realtime_local_simulation:
            raise ValidationError("varip is unsupported without realtime rollback semantics")
        self.parity_safe = False
        self.unsupported_features.add("varip_local_simulation")
        self.parity_risks.append(
            "allow_realtime_local_simulation override used with varip; state persistence is local simulation only"
        )

    def _strategy_calc_on_every_tick_enabled(self, declaration: ASTNode) -> bool:
        call = declaration.child("call")
        if call is None:
            return False
        for name, value_node in self._call_arguments(call):
            if name != "calc_on_every_tick":
                continue
            if value_node.kind == "Literal":
                return bool(literal_value(value_node))
            rendered = self.translate_expression(value_node)
            return rendered == "True"
        return False

    def _emit_module(
        self, program: ASTProgram, declaration: ASTNode, *, title: str, module_name: str
    ) -> None:
        self._collect_globals(program)
        self._declare_base_imports()
        self._declare_dynamic_imports(program)
        self.emitter.line("# Generated by AST2Python")
        self.emitter.line(f"# Pine runtime contract: {RUNTIME_CONTRACT_VERSION}")
        self.emitter.line(f"# Source: {module_name}.pine")
        self.emitter.line()
        self.emitter.line("from __future__ import annotations")
        self.emitter.line()
        for line in self.ctx.imports.render():
            self.emitter.line(line)
        self.emitter.line()
        self.emitter.line(f'REQUIRED_RUNTIME_CONTRACT = "{RUNTIME_CONTRACT_VERSION}"')
        self.emitter.line()
        self._emit_type_declarations(program)
        class_name = class_name_for_mode(self.ctx.mode)
        base_class = base_class_for_mode(self.ctx.mode)
        self.emitter.line(f"class {class_name}({base_class}):")
        self.emitter.indent()
        self.emitter.line('"""')
        self.emitter.line(f"Generated from Pine declaration: {title}")
        self.emitter.line('"""')
        self.emitter.line()
        self._emit_init(declaration)
        self.emitter.line()
        self._emit_function_declarations(program)
        self.emitter.line()
        self._emit_run()
        self.emitter.line()
        self._emit_snapshot()
        if self.ctx.mode != "library":
            self.emitter.line()
            self._emit_process_bar(program)
            # Emit _init_series after processing bar so global_series is complete
            self.emitter.line()
            self.emitter.line("def _init_series(self):")
            self.emitter.indent()
            if not self.global_series:
                self.emitter.line("pass")
            for info, dtype in self.global_series:
                self.emitter.line(
                    f'self.{info.py_name} = self.rt.series("{info.py_name}", dtype="{dtype}")'
                )
                self.emitter.line(f'self._var_initialized["{info.py_name}"] = False')
            self.emitter.dedent()
            self.emitter.line()
        self.emitter.dedent()

    def _declare_base_imports(self) -> None:
        self.ctx.imports.require_from("ast2python.errors", "RuntimeContractError")
        self.ctx.imports.require_from(
            "ast2python.runtime_contract.generated_base", base_class_for_mode(self.ctx.mode)
        )
        self.ctx.imports.require_from("pinelib.core", "PineRuntime")
        self.ctx.imports.require_from("pinelib.core", "na")
        self.ctx.imports.require_from("pinelib.core", "is_na")
        self.ctx.imports.require_from("pinelib.core", "pine_bool")
        for name in (
            "pine_add",
            "pine_sub",
            "pine_mul",
            "pine_div",
            "pine_eq",
            "pine_ne",
            "pine_gt",
            "pine_gte",
            "pine_lt",
            "pine_lte",
        ):
            self.ctx.imports.require_from("pinelib.core", name)
        self.ctx.imports.require_from("pinelib.request", "security", alias="request_security")
        if self.ctx.mode == "strategy":
            self.ctx.imports.require_from("pinelib.strategy", "StrategyContext")
            self.ctx.imports.require_from("pinelib.backtest", "run_generated_strategy")
        self.ctx.imports.require_from("pinelib.errors", "PineRuntimeError")
        self.ctx.imports.require_from("pinelib.errors", "PL_INPUT_VALIDATION_ERROR")

    def _declare_dynamic_imports(self, program: ASTProgram) -> None:
        """Predeclare imports needed by generated statements before rendering the header."""
        for node in program.descendants():
            if node.kind == "CallExpr":
                callee = node.child("callee")
                if callee is not None and member_chain(callee) == "request.security_lower_tf":
                    self.ctx.imports.require_from(
                        "pinelib.request", "security_lower_tf", alias="request_security_lower_tf"
                    )
            if node.kind in {"ForRangeStructure", "ForStructure"}:
                self.ctx.imports.require_from("pinelib.core", "pine_range")
            if node.kind == "ForInStructure":
                self.ctx.imports.require_from("builtins", "iter", alias="pine_iter")
            if node.kind in UDT_DECLARATIONS:
                self.ctx.imports.require_from("dataclasses", "dataclass")
            if node.kind in ENUM_DECLARATIONS:
                self.ctx.imports.require_from("enum", "Enum")
            if node.kind == "MemberAccessExpr":
                chain = member_chain(node)
                if chain is not None and chain.startswith("color."):
                    self.ctx.imports.require_from("pinelib", "color", alias="pine_color")
                if chain is not None and chain.startswith("ta."):
                    member = chain.split(".", 1)[1]
                    if member in DERIVED_BUILTIN_SERIES:
                        self.ctx.imports.require_from("pinelib.ta", f"{member}_series")
            # Scan for bare DERIVED_BUILTIN_SERIES identifiers (e.g., hlc3 in ta.cci(hlc3, 20))
            if node.kind == "Identifier":
                name = str(node.field("name"))
                if name in DERIVED_BUILTIN_SERIES:
                    self.ctx.imports.require_from("pinelib.ta", f"{name}_series")
            if node.kind != "CallExpr":
                continue
            callee = node.child("callee")
            chain = None if callee is None else member_chain(callee)
            if chain is None:
                continue
            if chain in {"na", "nz", "fixnan"}:
                self.ctx.imports.require_from("pinelib.core", "is_na" if chain == "na" else chain)
            if chain.startswith("ta."):
                member = chain.split(".", 1)[1]
                if member in DERIVED_BUILTIN_SERIES:
                    # ta.hl2, ta.hlc3, ta.ohlc4, ta.hlcc4 → need _series variant for rolling TA
                    self.ctx.imports.require_from("pinelib.ta", f"{member}_series")
                else:
                    sig = BUILTIN_SIGNATURES.get(chain)
                    if sig is not None:
                        fn = sig.builtin.split(".", 1)[1] if sig.builtin.startswith("ta.") else sig.builtin
                        self.ctx.imports.require_from("pinelib.ta", fn)
                    else:
                        self.ctx.imports.require_from("pinelib.ta", member)
            elif chain.startswith("math."):
                self.ctx.imports.require_from("pinelib.math", chain.split(".", 1)[1])
            elif chain.startswith("str."):
                self.ctx.imports.require_from("pinelib", "string", alias="pine_string")
            elif chain.startswith(("array.", "map.", "matrix.")):
                self.ctx.imports.require_from(
                    "pinelib.reference",
                    {"array": "PineArray", "map": "PineMap", "matrix": "PineMatrix"}[
                        chain.split(".", 1)[0]
                    ],
                )

    def _emit_init(self, declaration: ASTNode) -> None:
        self.emitter.line("def __init__(self, params=None, runtime=None):")
        self.emitter.indent()
        self.emitter.line("self.params = params or {}")
        self.emitter.line("self.rt = runtime")
        self.emitter.line("if self.rt is None:")
        self.emitter.indent()
        self.emitter.line('raise RuntimeContractError("runtime is required for generated modules")')
        self.emitter.dedent()
        self.emitter.line(
            "if getattr(self.rt, 'contract_version', None) != REQUIRED_RUNTIME_CONTRACT:"
        )
        self.emitter.indent()
        self.emitter.line(
            "raise RuntimeContractError("
            f'f"{CONTRACT_VERSION_MISMATCH}: requires runtime contract '
            "{REQUIRED_RUNTIME_CONTRACT}, got "
            "{getattr(self.rt, 'contract_version', None)}\""
            ")"
        )
        self.emitter.dedent()
        if self.ctx.mode == "strategy":
            self._emit_strategy_context(declaration)
            self.emitter.line("self.ctx.attach_runtime(self.rt)")
        else:
            self.emitter.line("self.ctx = None")
        self.emitter.line("self._var_initialized = {}")
        self.emitter.line("self.alerts = []")
        self.emitter.line("self.alert_conditions = []")
        self.emitter.line("self.external_library_calls = []")
        self.emitter.line("self.visual_calls = []")
        self.emitter.line("self._init_inputs()")
        self.emitter.dedent()
        self.emitter.line()
        self.emitter.line("def _record_alert(self, kind, *args, source_map=None, **kwargs):")
        self.emitter.indent()
        self.emitter.line(
            "payload = {'kind': kind, 'args': args, 'kwargs': kwargs, 'source_map': source_map}"
        )
        self.emitter.line(
            "(self.alert_conditions if kind == 'alertcondition' else self.alerts).append(payload)"
        )
        self.emitter.line("return None")
        self.emitter.dedent()
        self.emitter.line()
        self.emitter.line(
            "def _external_library_call(self, alias, member, *args, source_map=None, **kwargs):"
        )
        self.emitter.indent()
        self.emitter.line(
            "self.external_library_calls.append({'alias': alias, 'member': member, 'args': args, 'kwargs': kwargs, 'source_map': source_map})"  # noqa: E501
        )
        self.emitter.line("return na")
        self.emitter.dedent()
        self.emitter.line()
        self.emitter.line("def _visual_call(self, name, *args, source_map=None, **kwargs):")
        self.emitter.indent()
        self.emitter.line(
            "self.visual_calls.append({'name': name, 'args': args, 'kwargs': kwargs, 'source_map': source_map})"  # noqa: E501
        )
        self.emitter.line("if name.endswith('.new'):")
        self.emitter.indent()
        self.emitter.line("kind = name.split('.', 1)[0]")
        self.emitter.line(
            "positional = {'line': ('x1', 'y1', 'x2', 'y2'), 'label': ('x', 'y', 'text'), 'box': ('left', 'top', 'right', 'bottom'), 'table': ('position', 'columns', 'rows')}.get(kind, ())"  # noqa: E501
        )
        self.emitter.line("attrs = dict(kwargs)")
        self.emitter.line("attrs.update({key: value for key, value in zip(positional, args)})")
        self.emitter.line("return self.rt.visual.new(kind, **attrs)")
        self.emitter.dedent()
        self.emitter.line("if name.split('.', 1)[0] in {'line', 'label', 'box', 'table'} and args:")
        self.emitter.indent()
        self.emitter.line("kind, method = name.split('.', 1)")
        self.emitter.line("if method == 'delete':")
        self.emitter.indent()
        self.emitter.line("return self.rt.visual.delete(args[0])")
        self.emitter.dedent()
        self.emitter.line("attrs = dict(kwargs)")
        self.emitter.line("attrs['_method'] = method")
        self.emitter.line("attrs['_args'] = args[1:]")
        self.emitter.line("return self.rt.visual.set(args[0], **attrs)")
        self.emitter.dedent()
        self.emitter.line("return None")
        self.emitter.dedent()
        self.emitter.line()
        self.emitter.line("def _init_inputs(self):")
        self.emitter.indent()
        if not self.input_series:
            self.emitter.line("pass")
        for info, dtype, meta in self.input_series:
            default = meta["default_python"]
            schema = repr(meta["public"])
            self.emitter.line(
                f'self.{info.py_name} = self.rt.series("{info.py_name}", dtype="{dtype}")'
            )
            # For source inputs, bind directly to the Series reference instead of using
            # set_current with a scalar. This avoids the na-at-init problem because
            # the Series reference itself (not its current value) is used.
            if dtype == "source":
                # Strip .current from default to get the Series reference
                # e.g., "self.rt.close.current" -> "self.rt.close"
                source_ref = default.replace(".current", "") if isinstance(default, str) else default
                self.emitter.line(f'self.{info.py_name} = {source_ref}')
            else:
                self.emitter.line(
                    f'self.{info.py_name}.set_current(self._input_value("{info.pine_name}", {default}, {schema}))'  # noqa: E501
                )
        self.emitter.dedent()
        self.emitter.line()
        self.emitter.line("def _input_value(self, name, default, schema):")
        self.emitter.indent()
        self.emitter.line("value = self.params.get(name, default)")
        self.emitter.line("kind = schema.get('type')")
        self.emitter.line("def fail(message):")
        self.emitter.indent()
        self.emitter.line(
            "diagnostics = getattr(getattr(self.rt, 'config', None), 'diagnostics', None)"
        )
        self.emitter.line("if isinstance(diagnostics, list):")
        self.emitter.indent()
        self.emitter.line(
            "diagnostics.append({'code': PL_INPUT_VALIDATION_ERROR, 'message': message, 'input': name})"  # noqa: E501
        )
        self.emitter.dedent()
        self.emitter.line("raise PineRuntimeError(message, code=PL_INPUT_VALIDATION_ERROR)")
        self.emitter.dedent()
        self.emitter.line(
            "if kind == 'int' and (not isinstance(value, int) or isinstance(value, bool)):"
        )
        self.emitter.indent()
        self.emitter.line("fail(f'Input {name} must be int')")
        self.emitter.dedent()
        self.emitter.line(
            "if kind == 'float' and (not isinstance(value, (int, float)) or isinstance(value, bool)):"  # noqa: E501
        )
        self.emitter.indent()
        self.emitter.line("fail(f'Input {name} must be float')")
        self.emitter.dedent()
        self.emitter.line("if kind == 'bool' and not isinstance(value, bool):")
        self.emitter.indent()
        self.emitter.line("fail(f'Input {name} must be bool')")
        self.emitter.dedent()
        self.emitter.line(
            "if kind in {'string', 'session', 'timeframe'} and not isinstance(value, str):"
        )
        self.emitter.indent()
        self.emitter.line("fail(f'Input {name} must be string')")
        self.emitter.dedent()
        self.emitter.line("options = schema.get('options')")
        self.emitter.line("if options is not None and value not in options:")
        self.emitter.indent()
        self.emitter.line("fail(f'Input {name} must be one of {options!r}')")
        self.emitter.dedent()
        self.emitter.line("minval = schema.get('minval')")
        self.emitter.line("if minval is not None and value < minval:")
        self.emitter.indent()
        self.emitter.line("fail(f'Input {name} must be >= {minval!r}')")
        self.emitter.dedent()
        self.emitter.line("maxval = schema.get('maxval')")
        self.emitter.line("if maxval is not None and value > maxval:")
        self.emitter.indent()
        self.emitter.line("fail(f'Input {name} must be <= {maxval!r}')")
        self.emitter.dedent()
        self.emitter.line("return value")
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
        if self.ctx.mode == "strategy":
            self.emitter.line("def on_bar(self, runtime, strategy):")
            self.emitter.indent()
            self.emitter.line("bar = runtime.current_bar")
            self.emitter.line("if bar is None:")
            self.emitter.indent()
            self.emitter.line(
                'raise RuntimeContractError("strategy callback requires an active bar")'
            )
            self.emitter.dedent()
            self.emitter.line("self._process_bar(bar)")
            self.emitter.dedent()
            self.emitter.line()
            self.emitter.line("def run(self, bars):")
            self.emitter.indent()
            self.emitter.line("result = run_generated_strategy(self, self.rt, self.ctx, bars)")
            self.emitter.line("return result.report.snapshots")
            self.emitter.dedent()
            return
        self.emitter.line("def run(self, bars):")
        self.emitter.indent()
        self.emitter.line("results = []")
        self.emitter.line("for bar in bars:")
        self.emitter.indent()
        self.emitter.line("self.rt.begin_bar(bar)")
        self.emitter.line("try:")
        self.emitter.indent()
        if self.ctx.mode == "library":
            self.emitter.line("pass")
        else:
            self.emitter.line("self._process_bar(bar)")
            if self.ctx.mode == "strategy":
                self.emitter.line("self.ctx.process_orders_for_bar(runtime=self.rt, bar=bar)")
                if self.ctx.strategy_metadata.get("calc_on_order_fills") is True:
                    self.emitter.line("_recalc_count = 0")
                    self.emitter.line(
                        "while self.ctx.calc_on_order_fills and self.ctx.has_fill_recalc_pending():"
                    )
                    self.emitter.indent()
                    self.emitter.line("_recalc_count += 1")
                    self.emitter.line("self.rt.guard_recalc_count(_recalc_count)")
                    self.emitter.line("self.ctx.update_position_equity_trades_after_fill()")
                    self.emitter.line("self._process_bar(bar)")
                    self.emitter.line(
                        "self.ctx.process_orders_for_bar(runtime=self.rt, bar=bar, recalc_phase=True)"  # noqa: E501
                    )
                    self.emitter.dedent()
        self.emitter.dedent()
        self.emitter.line("finally:")
        self.emitter.indent()
        self.emitter.line("self.rt.end_bar()")
        self.emitter.dedent()
        if self.ctx.mode == "library":
            self.emitter.line("results.append(None)")
        else:
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
        # Call _init_series on first bar so global_series is complete
        self.emitter.line("if not getattr(self, '_series_initialized', False):")
        self.emitter.indent()
        self.emitter.line("self._init_series()")
        self.emitter.line("self._series_initialized = True")
        self.emitter.dedent()
        if not program.items:
            self.emitter.line("pass")
        for item in program.items:
            if (
                item.kind
                in FUNCTION_DECLARATIONS
                | METHOD_DECLARATIONS
                | UDT_DECLARATIONS
                | ENUM_DECLARATIONS
                or item.kind == "ImportDeclaration"
            ):
                continue
            self._emit_statement(item)
        self.emitter.dedent()

    def _collect_globals(self, program: ASTProgram) -> None:
        for item in program.items:
            if item.kind == "ImportDeclaration":
                self._record_import_alias(item)
                continue
            if item.kind in FUNCTION_DECLARATIONS:
                name = item.field("name")
                if name is not None:
                    self.functions.add(str(name))
                continue
            if item.kind in METHOD_DECLARATIONS:
                name = item.field("name")
                if name is not None:
                    self.methods.add(str(name))
                continue
            if item.kind in UDT_DECLARATIONS | ENUM_DECLARATIONS:
                continue
            if item.kind in {"AlertCondition"}:
                continue
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
                    if initializer is not None:
                        info.type_info = self._infer_type_info(initializer)
                        self.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = (
                            info.type_info.to_dict()
                        )
                    elif info.type_ref in {"line", "label", "box", "table", "PineObjectId"}:
                        info.type_info = make_type_info(
                            "PineObjectId", info.qualifier, is_series=info.is_series
                        )
                        self.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = (
                            info.type_info.to_dict()
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
                    info.type_info = make_type_info(
                        meta["type"],
                        "input",
                        is_series=True,
                        can_be_na=meta["type"] != "bool",
                    )
                    self.ctx.type_metadata[f"global:{info.pine_name}"] = info.type_info.to_dict()
                    self.input_series.append((info, meta["type"], meta))
                    self.ctx.input_metadata.append(meta["public"])
                    callee = initializer.child("callee")
                    chain = None if callee is None else member_chain(callee)
                    if chain is not None:
                        self.ctx.coverage.builtin(chain)
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
                    if initializer is not None:
                        info.type_info = self._infer_type_info(initializer)
                        self.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = (
                            info.type_info.to_dict()
                        )
                    elif info.type_ref in {"line", "label", "box", "table", "PineObjectId"}:
                        info.type_info = make_type_info(
                            "PineObjectId", info.qualifier, is_series=info.is_series
                        )
                        self.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = (
                            info.type_info.to_dict()
                        )
                    self.global_series.append((info, self._infer_dtype(initializer)))

    def _emit_statement(self, node: ASTNode) -> None:
        self.ctx.coverage.generated()
        self.emitter.source_comment(node.loc, node.source)
        if node.kind == "ImportDeclaration":
            self._record_import_alias(node)
            return
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
            self.emitter.line(
                self.translate_expression(expression), loc=node.loc, source=node.source
            )
            return
        if node.kind == "IfStructure":
            self._emit_if(node)
            return
        if node.kind in {"SwitchStructure", "SwitchStatement"}:
            self._emit_switch(node)
            return
        if node.kind in {"ForRangeStructure", "ForStructure"}:
            self._emit_for_range(node)
            return
        if node.kind == "ForInStructure":
            self._emit_for_in(node)
            return
        if node.kind in {"WhileStructure", "WhileStatement"}:
            self._emit_while(node)
            return
        if node.kind == "BreakStatement":
            self.emitter.line("break", loc=node.loc, source=node.source)
            return
        if node.kind == "ContinueStatement":
            self.emitter.line("continue", loc=node.loc, source=node.source)
            return
        if node.kind == "Block":
            for statement in node.children("statements"):
                self._emit_statement(statement)
            return
        if node.kind == "AlertCondition":
            self._emit_alert_condition(node)
            return
        self._unsupported(node, f"Unsupported statement node: {node.kind}")

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
            if initializer is not None:
                info.type_info = self._infer_type_info(initializer)
                self.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = (
                    info.type_info.to_dict()
                )
            elif info.type_ref in {"line", "label", "box", "table", "PineObjectId"}:
                info.type_info = make_type_info(
                    "PineObjectId", info.qualifier, is_series=info.is_series
                )
                self.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = (
                    info.type_info.to_dict()
                )
            if is_global:
                self.global_series.append((info, self._infer_dtype(initializer)))
            return info

    def _varip_key(self, info: VariableInfo) -> str:
        return f"{info.scope_id}:{info.pine_name}"

    def _emit_var_declaration(self, node: ASTNode) -> None:
        name = str(node.field("name"))
        initializer = node.child("initializer")
        if initializer is None:
            raise UnsupportedNodeError(f"VarDeclaration {name} missing initializer")
        if self._is_input_call(initializer):
            return
        info = self._resolve_or_declare_var(node, name, initializer)
        expr = self.translate_expression(initializer)
        if self.ctx.current_scope.kind == "global":
            if info.declaration_kind == "varip":
                key = self._varip_key(info)
                self.emitter.line(
                    f'if not self._var_initialized["{info.py_name}"]:',
                    loc=node.loc,
                    source=node.source,
                )
                self.emitter.indent()
                self.emitter.line(
                    f'self.{info.py_name}.set_current(self.rt.get_varip_state("{key}", lambda: {expr}))'
                )
                self.emitter.line(f'self._var_initialized["{info.py_name}"] = True')
                self.emitter.dedent()
                self.emitter.line("else:")
                self.emitter.indent()
                self.emitter.line(
                    f'self.{info.py_name}.set_current(self.rt.get_varip_state("{key}", lambda: self.{info.py_name}.current))'
                )
                self.emitter.dedent()
            elif info.declaration_kind == "var":
                self.emitter.line(
                    f'if not self._var_initialized["{info.py_name}"]:',
                    loc=node.loc,
                    source=node.source,
                )
                self.emitter.indent()
                self.emitter.line(f"self.{info.py_name}.set_current({expr})")
                self.emitter.line(f'self._var_initialized["{info.py_name}"] = True')
                self.emitter.dedent()
            else:
                self.emitter.line(
                    f"self.{info.py_name}.set_current({expr})", loc=node.loc, source=node.source
                )
            return
        if info.declaration_kind == "varip":
            self.emitter.line(
                f'{info.py_name} = self.rt.get_varip_state("{self._varip_key(info)}", lambda: {expr})',
                loc=node.loc,
                source=node.source,
            )
        else:
            self.emitter.line(f"{info.py_name} = {expr}", loc=node.loc, source=node.source)

    def _tuple_targets(self, node: ASTNode) -> list[str]:
        raw_targets = (
            node.raw.get("targets") or node.raw.get("names") or node.raw.get("elements") or []
        )
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
                elif target.kind == "TupleTarget":
                    # Pine v6 uses TupleTarget for tuple destructuring: [a, b] = ta.macd(...)
                    targets.append(str(target.field("name")))
                else:
                    raise UnsupportedNodeError(f"Unsupported tuple target: {target.kind}")
        return targets

    # Known tuple-returning builtins and their element types (index -> type)
    # Used for tuple destructuring type extraction: [a, b] = ta.macd(...) -> a:float, b:float
    TUPLE_RETURNING_BUILTINS: dict[str, tuple[str, ...]] = {
        "ta.macd": ("float", "float", "float"),
        "ta.bb": ("float", "float", "float"),  # basis, upper, lower
        "ta.supertrend": ("float", "int"),  # line, direction
        "ta.dmi": ("float", "float", "float"),  # plus, minus, adx
    }

    def _emit_tuple_declaration(self, node: ASTNode) -> None:
        initializer = node.child("initializer") or node.child("value")
        if initializer is None:
            raise UnsupportedNodeError("TupleDeclaration missing initializer")
        targets = self._tuple_targets(node)
        if not targets:
            raise UnsupportedNodeError("TupleDeclaration has no targets")
        # Determine tuple element types for type metadata
        tuple_element_types: list[str] | None = None
        if initializer.kind == "CallExpr":
            callee = initializer.child("callee")
            chain = member_chain(callee) if callee else None
            if chain in self.TUPLE_RETURNING_BUILTINS:
                tuple_element_types = list(self.TUPLE_RETURNING_BUILTINS[chain])
        temp_names: list[str] = []
        assignments: list[tuple[VariableInfo | None, str]] = []
        for index, name in enumerate(targets, start=1):
            if name == "_":
                temp_names.append(f"_discard_{index}")
                assignments.append((None, temp_names[-1]))
                continue
            info = self._resolve_or_declare_var(node, name, initializer)
            # Extract element type from known tuple-returning builtins
            if tuple_element_types is not None and index <= len(tuple_element_types):
                elem_base = tuple_element_types[index - 1]
                info.type_info = make_type_info(elem_base, "series", is_series=True)
                self.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = (
                    info.type_info.to_dict()
                )
                # Override dtype in global_series to the element type, not tuple
                for i, (gs_info, gs_dtype) in enumerate(self.global_series):
                    if gs_info is info:
                        self.global_series[i] = (info, elem_base)
                        break
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
                value_expr = rhs
            else:
                operator = str(node.field("op")).replace("=", "")
                value_expr = self._lower_binary_operator(
                    operator, f"self.{info.py_name}.current", rhs, node
                )
            self.emitter.line(
                f"self.{info.py_name}.set_current({value_expr})", loc=node.loc, source=node.source
            )
            if info.declaration_kind == "varip":
                self.emitter.line(
                    f'self.rt.varip_state["{self._varip_key(info)}"] = self.{info.py_name}.current'
                )
            return
        if node.field("op") in {":=", "="}:
            value_expr = rhs
        else:
            operator = str(node.field("op")).replace("=", "")
            value_expr = self._lower_binary_operator(operator, info.py_name, rhs, node)
        self.emitter.line(f"{info.py_name} = {value_expr}", loc=node.loc, source=node.source)
        if info.declaration_kind == "varip":
            self.emitter.line(f'self.rt.varip_state["{self._varip_key(info)}"] = {info.py_name}')

    def _emit_if(self, node: ASTNode) -> None:
        condition = node.child("condition")
        then_block = node.child("then_block")
        else_block = node.child("else_block")
        if condition is None or then_block is None:
            raise UnsupportedNodeError("IfStructure missing condition or then_block")
        self._reject_visual_value(condition)
        self.emitter.line(
            f"if pine_bool({self.translate_expression(condition)}):",
            loc=node.loc,
            source=node.source,
        )
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
            self._reject_visual_value(branch_condition)
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
            self.emitter.line(
                f"for {loop_name} in pine_range({start}, {end}, {step}):",
                loc=node.loc,
                source=node.source,
            )
        else:
            self.emitter.line(
                f"for {loop_name} in pine_range({start}, {end}):", loc=node.loc, source=node.source
            )
        self.emitter.indent()
        body = node.child("body")
        if body is None or not body.children("statements"):
            self.emitter.line("pass")
        else:
            for statement in body.children("statements"):
                self._emit_statement(statement)
        self.emitter.dedent()
        self.ctx.exit_scope()

    def _for_in_target_names(self, node: ASTNode) -> list[str]:
        target = node.child("target")
        raw_names: Any = None if target is None else target.raw.get("names")
        if raw_names is None:
            raw_names = (
                node.raw.get("names") or node.raw.get("variables") or node.raw.get("targets")
            )
        if isinstance(raw_names, list):
            return [str(item) for item in raw_names]
        if isinstance(raw_names, str):
            return [raw_names]
        if target is not None and target.kind == "Identifier":
            return [str(target.field("name"))]
        self._unsupported(node, "ForInStructure target is unsupported")

    def _emit_for_in(self, node: ASTNode) -> None:
        iterable_node = node.child("iterable") or node.child("collection")
        body = node.child("body")
        if iterable_node is None:
            self._unsupported(node, "ForInStructure requires iterable")
        names = self._for_in_target_names(node)
        iterable = self.translate_expression(iterable_node)
        self.ctx.enter_scope("loop")
        py_names: list[str] = []
        for name in names:
            info = self.ctx.declare_var(
                name,
                type_ref=None,
                qualifier=None,
                declaration_kind="loop",
                is_series=False,
                is_mutable=True,
                loc=node.loc,
                prefer_py_name=name,
            )
            py_names.append(info.py_name)
        target = py_names[0] if len(py_names) == 1 else f"({', '.join(py_names)})"
        self.emitter.line(f"for {target} in {iterable}:", loc=node.loc, source=node.source)
        self.emitter.indent()
        statements = [] if body is None else body.children("statements")
        if statements:
            for statement in statements:
                self._emit_statement(statement)
        else:
            self.emitter.line("pass")
        self.emitter.dedent()
        self.ctx.exit_scope()

    def _emit_alert_condition(self, node: ASTNode) -> None:
        args = []
        condition = node.child("condition") or node.child("expression")
        if condition is not None:
            args.append(self.translate_expression(condition))
        title = node.child("title")
        message = node.child("message")
        kwargs = []
        if title is not None:
            kwargs.append(f"title={self.translate_expression(title)}")
        if message is not None:
            kwargs.append(f"message={self.translate_expression(message)}")
        self.ctx.coverage.builtin("alertcondition")
        self.emitter.line(
            f"self._record_alert('alertcondition'{', ' if args or kwargs else ''}{', '.join(args + kwargs)}, source_map=\"{node.loc.source_map if node.loc else ''}\")",  # noqa: E501
            loc=node.loc,
            source=node.source,
        )

    def _unsupported(self, node: ASTNode, message: str) -> NoReturn:
        self.ctx.add_diagnostic(
            UNSUPPORTED_NODE,
            message,
            Severity.ERROR,
            location=node.loc,
            details={"kind": node.kind},
        )
        self.ctx.coverage.unsupported()
        raise UnsupportedNodeError(message)

    def _record_import_alias(self, node: ASTNode) -> None:
        alias = node.field("alias") or node.field("library")
        if alias is None:
            return
        if not self.allow_external_library_stubs:
            self.ctx.add_diagnostic(
                EXTERNAL_LIBRARY_CALL,
                "external library imports are rejected in parity/default mode",
                Severity.ERROR,
                location=node.loc,
                details={"alias": str(alias), "path": node.field("path")},
            )
            raise UnsupportedBuiltinError(
                "external library imports require allow_external_library_stubs"
            )
        self.parity_safe = False
        self.unsupported_features.add("external_library_stubs")
        self.parity_risks.append("external library import lowered to recorder stub")
        self.ctx.import_aliases[str(alias)] = {
            "path": node.field("path"),
            "owner": node.field("owner"),
            "library": node.field("library"),
            "version": node.field("version"),
            "alias": str(alias),
        }

    def _emit_while(self, node: ASTNode) -> None:
        condition = node.child("condition")
        body = node.child("body") or node.child("block")
        if condition is None:
            raise UnsupportedNodeError("WhileStructure requires condition")
        guard = self.ctx.naming.reserve("while_guard", prefer="_guard")
        self.emitter.line(f"{guard} = 0", loc=node.loc, source=node.source)
        self._reject_visual_value(condition)
        self.emitter.line(
            f"while pine_bool({self.translate_expression(condition)}):",
            loc=node.loc,
            source=node.source,
        )
        self.emitter.indent()
        self.ctx.enter_scope("loop")
        self.emitter.line(f"{guard} += 1")
        self.emitter.line(
            f"if {guard} > getattr(getattr(self.rt, 'config', None), 'max_loop_iterations', 100000):"  # noqa: E501
        )
        self.emitter.indent()
        self.emitter.line('raise RuntimeContractError("max_loop_iterations exceeded")')
        self.emitter.dedent()
        if body is None or not body.children("statements"):
            self.emitter.line("pass")
        else:
            for statement in body.children("statements"):
                self._emit_statement(statement)
        self.ctx.exit_scope()
        self.emitter.dedent()

    def _switch_cases(self, node: ASTNode) -> list[ASTNode]:
        return node.children("cases", "branches", "arms")

    def _case_condition(self, case: ASTNode) -> ASTNode | None:
        return (
            case.child("condition")
            or case.child("match")
            or case.child("value")
            or case.child("test")
        )

    def _case_body(self, case: ASTNode) -> ASTNode | None:
        return case.child("body") or case.child("block") or case.child("then")

    def _emit_switch(self, node: ASTNode) -> None:
        subject = node.child("expression") or node.child("subject") or node.child("target")
        emitted = False
        for case in self._switch_cases(node):
            cond = self._case_condition(case)
            body = self._case_body(case)
            is_default = cond is None or bool(case.field("default", default=False))
            if is_default:
                self.emitter.line(
                    "else:" if emitted else "if True:",
                    loc=case.loc or node.loc,
                    source=case.source or node.source,
                )
            else:
                if subject is not None:
                    assert cond is not None
                    rendered = (
                        f"{self.translate_expression(subject)} == {self.translate_expression(cond)}"
                    )
                    prefix = "elif" if emitted else "if"
                    self.emitter.line(
                        f"{prefix} {rendered}:",
                        loc=case.loc or node.loc,
                        source=case.source or node.source,
                    )
                else:
                    assert cond is not None
                    self._reject_visual_value(cond)
                    prefix = "elif" if emitted else "if"
                    self.emitter.line(
                        f"{prefix} pine_bool({self.translate_expression(cond)}):",
                        loc=case.loc or node.loc,
                        source=case.source or node.source,
                    )
            emitted = True
            self.emitter.indent()
            statements = [] if body is None else body.children("statements")
            if statements:
                self.ctx.enter_scope("block")
                for statement in statements:
                    self._emit_statement(statement)
                self.ctx.exit_scope()
            else:
                expr = case.child("expression") or case.child("result")
                if expr is not None:
                    self.emitter.line(self.translate_expression(expr))
                else:
                    self.emitter.line("pass")
            self.emitter.dedent()
        if not emitted:
            self.emitter.line("pass", loc=node.loc, source=node.source)

    def _emit_type_declarations(self, program: ASTProgram) -> None:
        emitted = False
        for item in program.items:
            if item.kind in UDT_DECLARATIONS:
                self._emit_udt_declaration(item)
                emitted = True
            elif item.kind in ENUM_DECLARATIONS:
                self._emit_enum_declaration(item)
                emitted = True
        if emitted:
            self.emitter.line()

    def _emit_udt_declaration(self, node: ASTNode) -> None:
        name = str(node.field("name"))
        self.emitter.line("@dataclass", loc=node.loc, source=node.source)
        self.emitter.line(f"class {name}:")
        self.emitter.indent()
        fields = node.children("fields", "members")
        if not fields:
            self.emitter.line("pass")
        for field_node in fields:
            field_name = str(field_node.field("name"))
            type_name = self._type_ref_name(field_node) or str(field_node.field("type") or "object")
            default_node = field_node.child("default") or field_node.child("initializer")
            default = (
                self.translate_expression(default_node)
                if default_node is not None
                else self._default_for_type(type_name)
            )
            self.emitter.line(
                f"{snake_case(field_name)}: {self._python_type_name(type_name)} = {default}"
            )
        self.emitter.dedent()
        self.emitter.line()

    def _emit_enum_declaration(self, node: ASTNode) -> None:
        name = str(node.field("name"))
        self.emitter.line(f"class {name}(Enum):", loc=node.loc, source=node.source)
        self.emitter.indent()
        values = node.children("values", "members", "fields")
        if not values:
            self.emitter.line("pass")
        for value in values:
            raw = str(value.field("name") or value.field("value"))
            self.emitter.line(f"{snake_case(raw).upper()} = {raw!r}")
        self.emitter.dedent()
        self.emitter.line()

    def _emit_function_declarations(self, program: ASTProgram) -> None:
        emitted = False
        for item in program.items:
            if item.kind in FUNCTION_DECLARATIONS | METHOD_DECLARATIONS:
                self._emit_function_declaration(item)
                self.emitter.line()
                emitted = True
        if not emitted:
            self.emitter.line("# no user functions")

    def _param_name(self, node: ASTNode) -> str:
        return snake_case(str(node.field("name") or node.field("identifier") or "arg"))

    def _emit_function_declaration(self, node: ASTNode) -> None:
        name = snake_case(str(node.field("name")))
        params = node.children("params", "parameters", "arguments")
        py_params = [self._param_name(param) for param in params]
        self.emitter.line(
            f"def {name}(self{', ' if py_params else ''}{', '.join(py_params)}):",
            loc=node.loc,
            source=node.source,
        )
        self.emitter.indent()
        self.ctx.enter_scope("function")
        for param, py_name in zip(params, py_params, strict=False):
            info = self.ctx.declare_var(
                str(param.field("name") or py_name),
                type_ref=self._type_ref_name(param),
                qualifier=None,
                declaration_kind="param",
                is_series=False,
                is_mutable=True,
                loc=param.loc,
                prefer_py_name=py_name,
            )
            info.py_name = py_name
        body = node.child("body") or node.child("block")
        statements = [] if body is None else body.children("statements")
        if not statements:
            expr = node.child("expression") or node.child("result")
            if expr is None and body is not None and body.kind != "Block":
                expr = body
            self.emitter.line(
                f"return {self.translate_expression(expr)}" if expr is not None else "return None"
            )
        else:
            for index, statement in enumerate(statements):
                if index == len(statements) - 1 and statement.kind == "ExpressionStatement":
                    expr = statement.child("expression")
                    self.emitter.source_comment(statement.loc, statement.source)
                    self.emitter.line(
                        f"return {self.translate_expression(expr)}"
                        if expr is not None
                        else "return None",
                        loc=statement.loc,
                        source=statement.source,
                    )
                else:
                    self._emit_statement(statement)
        self.ctx.exit_scope()
        self.emitter.dedent()

    def _python_type_name(self, pine_type: str | None) -> str:
        return {"int": "int", "float": "float", "bool": "bool", "string": "str", "str": "str"}.get(
            str(pine_type), "object"
        )

    def _default_for_type(self, pine_type: str | None) -> str:
        return {"int": "0", "float": "na", "bool": "False", "string": "''", "str": "''"}.get(
            str(pine_type), "na"
        )

    def _is_visual_method_call(self, name: str) -> bool:
        if not name.startswith(VISUAL_OBJECT_METHOD_PREFIXES):
            return False
        suffix = name.split(".", 1)[1]
        return suffix.startswith("set_") or suffix in {"delete", "copy"}

    def _reject_visual_value(self, node: ASTNode | None) -> None:
        if node is None:
            return
        info = self._infer_type_info(node)
        if info.base_type == "PineObjectId":
            self.ctx.add_diagnostic(
                VISUAL_OBJECT_USED_AS_VALUE,
                "visual object id used as arithmetic/bool value is not supported",
                Severity.ERROR,
                location=node.loc,
            )
            raise TypeResolutionError("Visual object id cannot be used as a value")

    def _translate_switch_expression(self, node: ASTNode, *, runtime_expr: str) -> str:
        subject = node.child("expression") or node.child("subject") or node.child("target")
        default = "na"
        clauses: list[tuple[str, str]] = []
        for case in self._switch_cases(node):
            cond = self._case_condition(case)
            expr = case.child("expression") or case.child("result")
            body = self._case_body(case)
            if body is None:
                body_expr = None
            elif body.kind == "Block":
                body_expr = self._block_expression(body, runtime_expr=runtime_expr)
            else:
                body_expr = self.translate_expression(body, runtime_expr=runtime_expr)
            value = (
                self.translate_expression(expr, runtime_expr=runtime_expr)
                if expr is not None
                else (body_expr or "na")
            )
            if cond is None or bool(case.field("default", default=False)):
                default = value
            elif subject is not None:
                assert cond is not None
                clauses.append(
                    (
                        f"{self.translate_expression(subject, runtime_expr=runtime_expr)} == {self.translate_expression(cond, runtime_expr=runtime_expr)}",  # noqa: E501
                        value,
                    )
                )
            else:
                assert cond is not None
                self._reject_visual_value(cond)
                clauses.append(
                    (
                        f"pine_bool({self.translate_expression(cond, runtime_expr=runtime_expr)})",
                        value,
                    )
                )
        rendered = default
        for cond_text, value in reversed(clauses):
            rendered = f"({value} if {cond_text} else {rendered})"
        return rendered

    def _lower_binary_operator(self, op: str, left: str, right: str, node: ASTNode) -> str:
        pine_ops = {
            "+": "pine_add",
            "-": "pine_sub",
            "*": "pine_mul",
            "/": "pine_div",
            "==": "pine_eq",
            "!=": "pine_ne",
            ">": "pine_gt",
            ">=": "pine_gte",
            "<": "pine_lt",
            "<=": "pine_lte",
        }
        if op in pine_ops:
            return f"{pine_ops[op]}({left}, {right})"
        if op == "%":
            return f"({left} % {right})"
        if op == "and":
            return f"(pine_bool({left}) and pine_bool({right}))"
        if op == "or":
            return f"(pine_bool({left}) or pine_bool({right}))"
        self._unsupported(node, f"Unsupported binary operator: {op}")

    def translate_expression(self, node: ASTNode, *, runtime_expr: str = "self.rt") -> str:
        self.ctx.coverage.generated()
        if node.kind == "Literal":
            return "na" if node.field("literal_type") == "na" else repr(literal_value(node))
        if node.kind == "Identifier":
            return self._translate_identifier(node, runtime_expr=runtime_expr)
        if node.kind == "MemberAccessExpr":
            return self._translate_member_access(node, runtime_expr=runtime_expr)
        if node.kind == "BinaryExpr":
            left_node = node.child("left")
            right_node = node.child("right")
            if left_node is None or right_node is None:
                raise UnsupportedNodeError("BinaryExpr requires left and right operands")
            self._reject_visual_value(left_node)
            self._reject_visual_value(right_node)
            left = self.translate_expression(left_node, runtime_expr=runtime_expr)
            right = self.translate_expression(right_node, runtime_expr=runtime_expr)
            op = str(node.field("op"))
            return self._lower_binary_operator(op, left, right, node)
        if node.kind == "UnaryExpr":
            operand_node = node.child("operand")
            if operand_node is None:
                raise UnsupportedNodeError("UnaryExpr requires an operand")
            operand = self.translate_expression(operand_node, runtime_expr=runtime_expr)
            op = str(node.field("op"))
            if op == "not":
                return f"(not pine_bool({operand}))"
            if op == "-":
                return f"pine_mul(-1, {operand})"
            if op == "+":
                return operand
            self._unsupported(node, f"Unsupported unary operator: {op}")
        if node.kind in {"HistoryRefExpr", "HistoryReference", "SubscriptExpr", "IndexExpr"}:
            return self._translate_history_reference(node, runtime_expr=runtime_expr)
        if node.kind == "ConditionalExpr":
            condition_node = node.child("condition")
            true_node = node.child("then")
            false_node = node.child("else")
            if condition_node is None or true_node is None or false_node is None:
                raise UnsupportedNodeError("ConditionalExpr requires condition/then/else")
            self._reject_visual_value(condition_node)
            condition = self.translate_expression(condition_node, runtime_expr=runtime_expr)
            when_true = self.translate_expression(true_node, runtime_expr=runtime_expr)
            when_false = self.translate_expression(false_node, runtime_expr=runtime_expr)
            return f"({when_true} if pine_bool({condition}) else {when_false})"
        if node.kind == "IfStructure":
            return self._translate_if_expression(node, runtime_expr=runtime_expr)
        if node.kind in {"SwitchStructure", "SwitchExpr", "SwitchExpression"}:
            return self._translate_switch_expression(node, runtime_expr=runtime_expr)
        if node.kind == "TupleExpr":
            return (
                "("
                + ", ".join(
                    self.translate_expression(item, runtime_expr=runtime_expr)
                    for item in node.children("elements", "items", "values")
                )
                + ",)"
            )
        if node.kind == "ArrayLiteral":
            self.ctx.imports.require_from("pinelib.reference", "PineArray")
            return (
                "PineArray(["
                + ", ".join(
                    self.translate_expression(item, runtime_expr=runtime_expr)
                    for item in node.children("elements", "items", "values")
                )
                + "])"
            )
        if node.kind == "MapLiteral":
            self.ctx.imports.require_from("pinelib.reference", "PineMap")
            entries = []
            for item in node.children("entries", "items"):
                key = item.child("key")
                value = item.child("value")
                if key is None or value is None:
                    self._unsupported(item, "MapLiteral entry requires key/value")
                entries.append(
                    f"{self.translate_expression(key, runtime_expr=runtime_expr)}: {self.translate_expression(value, runtime_expr=runtime_expr)}"  # noqa: E501
                )
            return "PineMap({" + ", ".join(entries) + "})"
        if node.kind == "MatrixLiteral":
            self._unsupported(
                node, "MatrixLiteral lowering requires shape-preserving PineLib constructor support"
            )
        if node.kind == "CallExpr":
            return self._translate_call(node, runtime_expr=runtime_expr)
        self._unsupported(node, f"Unsupported expression node: {node.kind}")

    def _translate_scalar_operand(self, node: ASTNode, *, runtime_expr: str) -> str:
        if node.kind == "Identifier" and str(node.field("name")) in BUILTIN_SERIES:
            return f"{runtime_expr}.{node.field('name')}.current"
        return self.translate_expression(node, runtime_expr=runtime_expr)

    def _translate_identifier(self, node: ASTNode, *, runtime_expr: str) -> str:
        name = str(node.field("name"))
        if name in BUILTIN_SERIES:
            return f"{runtime_expr}.{name}.current"
        if name == "bar_index":
            return f"{runtime_expr}.bar_index_series.current"
        if name == "na":
            return "na"
        if name == "hl2":
            return f"pine_div(pine_add({runtime_expr}.high.current, {runtime_expr}.low.current), 2)"
        if name == "hlc3":
            return f"pine_div(pine_add(pine_add({runtime_expr}.high.current, {runtime_expr}.low.current), {runtime_expr}.close.current), 3)"  # noqa: E501
        if name == "ohlc4":
            return f"pine_div(pine_add(pine_add(pine_add({runtime_expr}.open.current, {runtime_expr}.high.current), {runtime_expr}.low.current), {runtime_expr}.close.current), 4)"  # noqa: E501
        if name == "hlcc4":
            return f"pine_div(pine_add(pine_add(pine_add({runtime_expr}.high.current, {runtime_expr}.low.current), {runtime_expr}.close.current), {runtime_expr}.close.current), 4)"  # noqa: E501
        info = self.ctx.resolve_var(name)
        if info.is_series:
            return f"self.{info.py_name}.current"
        return info.py_name

    def _translate_member_access(self, node: ASTNode, *, runtime_expr: str) -> str:
        chain = member_chain(node)
        obj = node.child("object")
        member = node.field("member")
        if chain is None:
            if obj is not None and isinstance(member, str):
                return f"({self.translate_expression(obj, runtime_expr=runtime_expr)}).{member}"
            raise UnsupportedNodeError("Invalid MemberAccessExpr")
        if chain.startswith("syminfo."):
            return f"{runtime_expr}.syminfo.{chain.split('.', 1)[1]}"
        if chain == "timeframe.period":
            return f"{runtime_expr}.timeframe.value"
        if chain.startswith("timeframe."):
            return f"{runtime_expr}.timeframe.{chain.split('.', 1)[1]}"
        if chain.startswith("barstate."):
            return f"{runtime_expr}.barstate.{chain.split('.', 1)[1]}"
        if chain == "strategy.long":
            return '"long"'
        if chain == "strategy.short":
            return '"short"'
        if chain.startswith("strategy.") and chain.split(".", 1)[1] in STRATEGY_READONLY_FIELDS:
            return f"self.ctx.{chain.split('.', 1)[1]}"
        if chain.startswith("strategy.commission."):
            return repr(chain.rsplit(".", 1)[-1])
        if chain == "strategy.cash":
            return '"cash"'
        if chain == "strategy.percent_of_equity":
            return '"percent_of_equity"'
        if chain == "strategy.fixed":
            return '"fixed"'
        if chain.startswith("strategy.oca."):
            return repr(chain.rsplit(".", 1)[-1])
        if chain.startswith("barmerge."):
            return repr(chain)
        if chain.startswith(
            ("display.", "currency.", "location.", "shape.", "size.", "position.", "plot.style_")
        ):
            return repr(chain)
        if chain.startswith("color."):
            self.ctx.imports.require_from("pinelib", "color", alias="pine_color")
            return f"pine_color.{chain.split('.', 1)[1]}"
        if chain.startswith("array."):
            return f"PineArray.{chain.split('.', 1)[1]}"
        if chain.startswith("map."):
            return f"PineMap.{chain.split('.', 1)[1]}"
        if chain.startswith("matrix."):
            return f"PineMatrix.{chain.split('.', 1)[1]}"
        if chain.startswith("request."):
            return f"{runtime_expr}.request.{chain.split('.', 1)[1]}"
        # Expand ta.hl2, ta.hlc3, ta.ohlc4, ta.hlcc4 using _RuntimeDerivedSeries.
        if chain.startswith("ta."):
            member = chain.split(".", 1)[1]
            if member in DERIVED_BUILTIN_SERIES:
                series_fn = f"{member}_series"
                self.ctx.imports.require_from("pinelib.ta", series_fn)
                return f"{series_fn}({runtime_expr})"
            # Other ta.* names (ta.sma, ta.ema, etc.) return as-is
            return chain
        if chain.startswith("math.") or chain.startswith("str."):
            return chain
        if chain.startswith(VISUAL_OBJECT_METHOD_PREFIXES):
            return chain
        if obj is not None and isinstance(member, str):
            return f"({self.translate_expression(obj, runtime_expr=runtime_expr)}).{member}"
        return chain

    def _translate_history_reference(self, node: ASTNode, *, runtime_expr: str) -> str:
        base = (
            node.child("base")
            or node.child("object")
            or node.child("target")
            or node.child("expression")
        )
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
            if info.type_info is not None and info.type_info.base_type in {
                "array",
                "map",
                "matrix",
            }:
                self.ctx.add_diagnostic(
                    REFERENCE_HISTORY_UNSUPPORTED,
                    "reference type history is unsupported by AST2Python v0.5.0 generation policy",
                    Severity.ERROR,
                    location=node.loc,
                    details={"name": name, "type": info.type_info.to_dict()},
                )
                raise TypeResolutionError("reference type history is unsupported")
            if info.is_series:
                return f"self.{info.py_name}[{offset}]"
        rendered = self.translate_expression(base, runtime_expr=runtime_expr)
        return f"{runtime_expr}.history({rendered}, {offset})"

    def _translate_if_expression(self, node: ASTNode, *, runtime_expr: str) -> str:
        condition = node.child("condition")
        then_expr = self._block_expression(node.child("then_block"), runtime_expr=runtime_expr)
        else_expr = self._block_expression(node.child("else_block"), runtime_expr=runtime_expr)
        if condition is None or then_expr is None or else_expr is None:
            raise UnsupportedNodeError(
                "IfStructure expression form requires expression-only branches"
            )
        return f"({then_expr} if pine_bool({self.translate_expression(condition, runtime_expr=runtime_expr)}) else {else_expr})"  # noqa: E501

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

    def _translate_user_func_arg(self, arg: ASTNode, runtime_expr: str) -> str:
        """Render a user-defined function argument, preserving Series for bare BUILTIN_SERIES.

        When a BUILTIN_SERIES identifier (close/high/low/etc.) is passed as a bare
        argument to a user-defined function, render it as self.rt.close (Series)
        instead of self.rt.close.current (scalar), so rolling/window TA inside the
        wrapper receives the full Series.
        """
        if arg.kind == "Identifier" and str(arg.field("name")) in BUILTIN_SERIES:
            return f"{runtime_expr}.{arg.field('name')}"
        return self.translate_expression(arg, runtime_expr=runtime_expr)

    def _translate_call(self, node: ASTNode, *, runtime_expr: str) -> str:
        callee = node.child("callee")
        if callee is None:
            raise UnsupportedNodeError("CallExpr missing callee")
        callee_chain = member_chain(callee)
        if callee_chain is None and callee.kind == "Identifier":
            callee_chain = str(callee.field("name"))
        if callee_chain is None:
            if callee.kind == "Literal" and callee.field("literal_type") == "na":
                return self._translate_na_helper_call("na", node, runtime_expr=runtime_expr)
            raise UnsupportedBuiltinError("Unsupported call target")
        if callee_chain == "request.security":
            return self._translate_request_security(node, runtime_expr=runtime_expr)
        if callee_chain == "request.security_lower_tf":
            return self._translate_request_security_lower_tf(node, runtime_expr=runtime_expr)
        if callee_chain.startswith("request."):
            return self._translate_unsupported_request_call(
                callee_chain, node, runtime_expr=runtime_expr
            )
        if callee_chain in DATE_HELPERS:
            return self._translate_date_helper_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain == "timestamp":
            return self._translate_timestamp_call(node)
        if callee_chain in {"time", "time_close"}:
            return self._translate_time_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain in {"na", "nz", "fixnan"}:
            return self._translate_na_helper_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain.startswith("strategy.") and callee_chain not in {
            "strategy.long",
            "strategy.short",
        }:
            return self._translate_strategy_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain in {"alert", "alertcondition"}:
            return self._translate_alert_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain in INPUT_CALLS:
            return self._translate_input_runtime_lookup(node)
        if callee_chain.startswith("ta."):
            return self._translate_ta_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain.startswith("math."):
            return self._translate_math_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain.startswith("str."):
            return self._translate_str_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain.startswith(("array.", "map.", "matrix.")):
            return self._translate_reference_call(callee_chain, node, runtime_expr=runtime_expr)
        alias = callee_chain.split(".", 1)[0]
        if alias in self.ctx.import_aliases and "." in callee_chain:
            return self._translate_external_library_call(
                callee_chain, node, runtime_expr=runtime_expr
            )
        if callee.kind == "MemberAccessExpr":
            obj = callee.child("object")
            member = callee.field("member")
            if obj is not None and isinstance(member, str) and member in self.methods:
                pieces = [self.translate_expression(obj, runtime_expr=runtime_expr)]
                pieces.extend(
                    self.translate_expression(arg, runtime_expr=runtime_expr)
                    for _, arg in self._call_arguments(node)
                )
                return f"self.{snake_case(member)}({', '.join(pieces)})"
        if (
            callee_chain in VISUAL_STATEMENT_CALLS
            or callee_chain in VISUAL_OBJECT_PRODUCERS
            or self._is_visual_method_call(callee_chain)
        ):
            return self._translate_visual_call(callee_chain, node, runtime_expr=runtime_expr)
        if callee_chain in self.functions:
            pieces = [self._translate_user_func_arg(arg, runtime_expr=runtime_expr) for _, arg in self._call_arguments(node)]
            return f"self.{snake_case(callee_chain)}({', '.join(pieces)})"
        if callee_chain in self.methods:
            pieces = [self._translate_user_func_arg(arg, runtime_expr=runtime_expr) for _, arg in self._call_arguments(node)]
            return f"self.{snake_case(callee_chain)}({', '.join(pieces)})"
        if callee_chain and callee_chain[:1].isupper():
            pieces = []
            for arg_name, arg in self._call_arguments(node):
                rendered = self.translate_expression(arg, runtime_expr=runtime_expr)
                pieces.append(rendered if arg_name is None else f"{arg_name}={rendered}")
            return f"{callee_chain}({', '.join(pieces)})"
        # Type-cast builtins: emit as direct Python builtins
        if callee_chain in {"int", "float", "bool", "str"}:
            pieces = [
                self.translate_expression(arg, runtime_expr=runtime_expr)
                for _, arg in self._call_arguments(node)
            ]
            return f"{callee_chain}({', '.join(pieces)})"
        self.ctx.add_diagnostic(
            UNKNOWN_OVERLOAD,
            f"unknown or unsupported call overload: {callee_chain}",
            Severity.ERROR if self.strict else Severity.WARNING,
            location=node.loc,
        )
        raise UnsupportedBuiltinError(callee_chain)

    def _translate_na_helper_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        arguments = self._call_arguments(node)
        if not arguments:
            raise UnsupportedBuiltinError(f"{name} requires at least one argument")
        first_type = self._infer_type_info(arguments[0][1])
        if first_type.base_type == "bool":
            self.ctx.add_diagnostic(
                BOOL_NA_OVERLOAD,
                f"Pine v6 bool values cannot be passed to {name}()",
                Severity.ERROR,
                location=arguments[0][1].loc,
                details={"builtin": name, "type": first_type.to_dict()},
            )
            raise TypeResolutionError(f"{name}() does not accept bool arguments in Pine v6")
        import_name = "is_na" if name == "na" else name
        self.ctx.imports.require_from("pinelib.core", import_name)
        rendered: list[str] = []
        for arg_name, arg in arguments:
            value = self.translate_expression(arg, runtime_expr=runtime_expr)
            rendered.append(value if arg_name is None else f"{arg_name}={value}")
        self.ctx.coverage.builtin(name)
        return f"{import_name}({', '.join(rendered)})"

    def _translate_request_security(self, node: ASTNode, *, runtime_expr: str) -> str:
        self._bind_or_raise("request.security", node)
        arguments = self._ordered_call_arguments("request.security", node)
        if len(arguments) < 3:
            raise UnsupportedBuiltinError("request.security requires at least 3 arguments")
        expression = arguments[2][1]
        self._diagnose_request_security_captures(expression)
        if self._contains_request_call(expression):
            severity = Severity.ERROR if self.strict else Severity.WARNING
            self.ctx.add_diagnostic(
                WARNING_NESTED_SECURITY,
                "request.security inside request.security expression may not be supported by PineLib MVP",  # noqa: E501
                severity,
                location=expression.loc,
            )
            self.ctx.add_diagnostic(
                NESTED_REQUEST_SECURITY,
                "nested request.security expression is diagnosed before runtime",
                severity,
                location=expression.loc,
            )
            if self.strict:
                raise UnsupportedBuiltinError(
                    "nested request.security is unsupported in strict mode"
                )
        state_id = state_id_for_call(self.ctx, node, "security")
        call_args = [
            self.translate_expression(arguments[0][1], runtime_expr=runtime_expr),
            self.translate_expression(arguments[1][1], runtime_expr=runtime_expr),
            f"lambda request_rt: {self.translate_expression(expression, runtime_expr='request_rt')}",  # noqa: E501
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
            ]
        )
        self.ctx.coverage.builtin("request.security")
        return f"request_security({', '.join(call_args + kwargs)})"

    def _translate_request_security_lower_tf(self, node: ASTNode, *, runtime_expr: str) -> str:
        self.ctx.imports.require_from(
            "pinelib.request", "security_lower_tf", alias="request_security_lower_tf"
        )
        self._bind_or_raise("request.security_lower_tf", node)
        arguments = self._ordered_call_arguments("request.security_lower_tf", node)
        if len(arguments) < 3:
            raise UnsupportedBuiltinError("request.security_lower_tf requires at least 3 arguments")
        expression = arguments[2][1]
        self._diagnose_request_security_lower_tf_safety(expression)
        state_id = state_id_for_call(self.ctx, node, "security_lower_tf")
        call_args = [
            self.translate_expression(arguments[0][1], runtime_expr=runtime_expr),
            self.translate_expression(arguments[1][1], runtime_expr=runtime_expr),
            f"lambda request_rt: {self.translate_expression(expression, runtime_expr='request_rt')}",  # noqa: E501
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
            ]
        )
        self.ctx.coverage.builtin("request.security_lower_tf")
        return f"request_security_lower_tf({', '.join(call_args + kwargs)})"

    def _translate_unsupported_request_call(
        self, name: str, node: ASTNode, *, runtime_expr: str, force_error: bool = False
    ) -> str:
        del runtime_expr
        severity = Severity.WARNING if self.allow_unsupported_request_stubs else Severity.ERROR
        self.ctx.add_diagnostic(
            UNSUPPORTED_REQUEST,
            f"{name} is recorded as unsupported by PineLib runtime_contract_v1.4/TZ_02 lowering",
            severity,
            location=node.loc,
            details={"builtin": name, "forced_error": force_error},
        )
        if not self.allow_unsupported_request_stubs:
            raise UnsupportedBuiltinError(name)
        self.parity_safe = False
        self.unsupported_features.add("unsupported_request_stub")
        self.parity_risks.append(f"{name} lowered to na stub")
        self.ctx.coverage.builtin(name)
        return "na"

    def _translate_external_library_call(
        self, name: str, node: ASTNode, *, runtime_expr: str
    ) -> str:
        del runtime_expr
        alias, member = name.split(".", 1)
        args: list[str] = []
        kwargs: list[str] = []
        for arg_name, arg in self._call_arguments(node):
            rendered = self.translate_expression(arg)
            if arg_name is None:
                args.append(rendered)
            else:
                kwargs.append(f"{arg_name}={rendered}")
        self.ctx.add_diagnostic(
            EXTERNAL_LIBRARY_CALL,
            f"external library call {name} lowered to runtime recorder returning na",
            Severity.WARNING,
            location=node.loc,
            details=self.ctx.import_aliases.get(alias),
        )
        self.ctx.coverage.builtin(name)
        return f'self._external_library_call({alias!r}, {member!r}{", " if args or kwargs else ""}{", ".join(args + kwargs)}, source_map="{node.loc.source_map if node.loc else ""}")'  # noqa: E501

    def _translate_alert_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        del runtime_expr
        args: list[str] = []
        kwargs: list[str] = []
        for arg_name, arg in self._call_arguments(node):
            rendered = self.translate_expression(arg)
            if arg_name is None:
                args.append(rendered)
            else:
                kwargs.append(f"{arg_name}={rendered}")
        self.ctx.coverage.builtin(name)
        return f'self._record_alert({name!r}{", " if args or kwargs else ""}{", ".join(args + kwargs)}, source_map="{node.loc.source_map if node.loc else ""}")'  # noqa: E501

    def _translate_date_helper_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        args = []
        for arg_name, arg in self._call_arguments(node):
            # Pine calendar helpers accept an optional timestamp, but PineLib v1 derives
            # calendar fields from the active runtime bar. Preserve supported named
            # arguments such as timezone and avoid emitting incompatible positionals.
            if arg_name is None:
                continue
            rendered = self.translate_expression(arg, runtime_expr=runtime_expr)
            args.append(f"{arg_name}={rendered}")
        args.append(f"runtime={runtime_expr}")
        self.ctx.coverage.builtin(name)
        return f"{runtime_expr}.timefunc.{name}({', '.join(args)})"

    def _translate_timestamp_call(self, node: ASTNode) -> str:
        """Lower Pine timestamp("YYYY-MM-DD HH:MM:SS +ZZZZ") to Unix milliseconds integer."""
        arguments = self._call_arguments(node)
        if not arguments:
            raise UnsupportedBuiltinError("timestamp requires at least one argument")
        arg_name, arg_expr = arguments[0]
        if arg_name is not None:
            raise UnsupportedBuiltinError(
                "timestamp does not support named arguments"
            )
        # Translate the argument to get the rendered string
        rendered = self.translate_expression(arg_expr)
        # Extract the string literal value
        literal_value = self._literal_or_rendered(arg_expr, rendered)
        if not isinstance(literal_value, str):
            raise UnsupportedBuiltinError(
                f"timestamp argument must be a string literal, got {type(literal_value).__name__}"
            )
        # Parse the Pine timestamp string format: "YYYY-MM-DD HH:MM:SS +ZZZZ"
        # Also support: "YYYY-MM-DDTHH:MM:SS+ZZZZ" (ISO variant)
        # and "YYYY-MM-DD HH:MM +ZZZZ" (no seconds)
        unix_ms = self._parse_pine_timestamp(literal_value)
        self.ctx.coverage.builtin("timestamp")
        return str(unix_ms)

    def _parse_pine_timestamp(self, s: str) -> int:
        """Parse Pine timestamp string to Unix milliseconds."""
        from datetime import datetime, timezone

        # Try formats in order of specificity
        formats = [
            "%Y-%m-%d %H:%M:%S %z",  # "2026-05-07 20:45:00 +0000"
            "%Y-%m-%dT%H:%M:%S%z",   # "2026-05-07T20:45:00+0000"
            "%Y-%m-%d %H:%M %z",      # "2026-05-07 20:45 +0000"
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(s, fmt)
                return int(dt.timestamp() * 1000)
            except ValueError:
                continue
        raise UnsupportedBuiltinError(
            f"timestamp: unsupported date format {s!r}. "
            "Supported: \"YYYY-MM-DD HH:MM:SS +ZZZZ\", \"YYYY-MM-DDTHH:MM:SS+ZZZZ\", \"YYYY-MM-DD HH:MM +ZZZZ\""
        )

    def _translate_reference_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        del runtime_expr
        self._bind_or_raise(name, node)
        namespace, method = name.split(".", 1)
        class_name = {"array": "PineArray", "map": "PineMap", "matrix": "PineMatrix"}[namespace]
        self.ctx.imports.require_from("pinelib.reference", class_name)
        if method == "copy":
            self.ctx.add_diagnostic(
                REFERENCE_COPY_POLICY,
                f"{name} uses explicit copy semantics; assignment otherwise preserves identity",
                Severity.WARNING,
                location=node.loc,
                details={"namespace": namespace, "method": method},
            )
        args = []
        for arg_name, arg in self._ordered_call_arguments(name, node):
            rendered = self.translate_expression(arg)
            args.append(rendered if arg_name is None else f"{arg_name}={rendered}")
        self.ctx.coverage.builtin(name)
        if namespace == "array" and method == "new":
            return f"PineArray({args[0] if args else 'None'})" if len(args) == 1 else "PineArray()"
        if namespace == "array" and method == "from":
            return f"PineArray([{', '.join(args)}])"
        if namespace == "map" and method == "new":
            return "PineMap()"
        if namespace == "matrix" and method == "new":
            return f"PineMatrix({', '.join(args)})"
        if method in {"push", "set", "put", "remove"} and args:
            return f"{args[0]}.{method}({', '.join(args[1:])})"
        if method in {"get", "size", "copy"} and args:
            if method == "size":
                return f"len({args[0]})"
            return f"{args[0]}.{method}({', '.join(args[1:])})"
        return f"{class_name}.{method}({', '.join(args)})"

    def _translate_time_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        arguments = self._call_arguments(node)
        func_name = "time" if name == "time" else "time_close"
        args = []
        for arg_name, arg in arguments:
            rendered = self.translate_expression(arg, runtime_expr=runtime_expr)
            args.append(rendered if arg_name is None else f"{arg_name}={rendered}")
        args.extend([f"runtime={runtime_expr}"])
        self.ctx.coverage.builtin(name)
        return f"{runtime_expr}.timefunc.{func_name}({', '.join(args)})"

    def _translate_strategy_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        if name not in STRATEGY_CALLS_P0:
            self.ctx.add_diagnostic(
                UNKNOWN_OVERLOAD,
                f"strategy API {name} is not part of AST2Python v0.7.0 P0 lowering set",
                Severity.ERROR if self.strict else Severity.WARNING,
                location=node.loc,
                details={"supported": sorted(STRATEGY_CALLS_P0)},
            )
            if self.strict:
                raise UnsupportedBuiltinError(name)
        self._bind_or_raise(name, node)
        method = name.split(".", 1)[1]
        arguments = self._ordered_call_arguments(name, node)
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
        self._bind_or_raise(name, node)
        arguments = self._ordered_call_arguments(name, node)
        pieces = []
        for arg_name, arg in arguments:
            rendered = self.translate_expression(arg, runtime_expr=runtime_expr)
            if arg_name is None:
                pieces.append(rendered)
            else:
                pieces.append(f"{arg_name}={rendered}")
        pieces.append(f'source_map="{node.loc.source_map if node.loc else ""}"')
        self.ctx.coverage.builtin(name)
        return f"self._visual_call({name!r}{', ' if pieces else ''}{', '.join(pieces)})"

    def _translate_input_runtime_lookup(self, node: ASTNode) -> str:
        arguments = self._call_arguments(node)
        if not arguments:
            raise UnsupportedBuiltinError("input.* requires a default value")
        default_node = arguments[0][1]
        if default_node.kind == "Literal":
            return repr(literal_value(default_node))
        return self.translate_expression(default_node)

    def _bind_or_raise(self, name: str, node: ASTNode) -> None:
        arg_nodes = self._call_arguments(node)
        arg_types = [(arg_name, self._infer_type_info(arg)) for arg_name, arg in arg_nodes]
        if name not in BUILTIN_SIGNATURES:
            self.ctx.add_diagnostic(
                BINDER_UNSUPPORTED_BUILTIN,
                f"{name} has no AST2Python semantic binder signature",
                Severity.ERROR,
                location=node.loc,
                details={"builtin": name, "arg_types": [info.to_dict() for _, info in arg_types]},
            )
            raise UnsupportedBuiltinError(name)
        errors = bind_builtin_call(name, arg_types)
        if not errors:
            return
        self.ctx.add_diagnostic(
            BINDER_SIGNATURE_MISMATCH,
            "; ".join(errors),
            Severity.ERROR,
            location=node.loc,
            details={
                "builtin": name,
                "arg_types": [info.to_dict() | {"name": arg_name} for arg_name, info in arg_types],
            },
        )
        if name in BUILTIN_SIGNATURES and not BUILTIN_SIGNATURES[name].codegen_supported:
            raise UnsupportedBuiltinError(name)
        raise TypeResolutionError(f"{name} semantic binding failed")

    def _ordered_call_arguments(self, name: str, node: ASTNode) -> list[tuple[str | None, ASTNode]]:
        spec = BUILTIN_SIGNATURES[name]
        raw = self._call_arguments(node)
        if spec.vararg is not None:
            return raw
        ordered: list[tuple[str | None, ASTNode] | None] = [None] * len(spec.parameters)
        extras: list[tuple[str | None, ASTNode]] = []
        name_to_index = {param.name: index for index, param in enumerate(spec.parameters)}
        seen_named = False
        for index, (arg_name, arg) in enumerate(raw):
            if arg_name is None and not seen_named:
                if index < len(ordered):
                    ordered[index] = (None, arg)
                continue
            if arg_name is None:
                extras.append((None, arg))
                continue
            seen_named = True
            if arg_name in name_to_index:
                ordered[name_to_index[arg_name]] = (arg_name, arg)
            else:
                extras.append((arg_name, arg))
        return [item for item in ordered if item is not None] + extras

    def _translate_series_source_argument(self, node: ASTNode, *, runtime_expr: str) -> str:
        """Render a Pine series object for TA helpers that inspect history internally.

        Most expression lowering returns the current scalar value for series identifiers
        because arithmetic and boolean expressions operate on the active bar. Helpers
        such as ta.crossover/ta.crossunder need both current and previous values, so
        passing ``self.fast.current`` loses history and makes every cross false. For
        plain series identifiers, pass the Series object itself. Complex expressions
        (Call, BinaryExpr, UnaryExpr, etc.) are materialized into a temp Series so
        that rolling/window TA functions receive a proper Series rather than a scalar.
        """
        # Handle derived builtin series used as function call args (e.g. ta.cci(ta.hlc3, 20)).
        # These are Call nodes where the callee is a MemberAccess to the ta namespace.
        if node.kind == "Call":
            callee = node.child("callee")
            if callee is not None and callee.kind == "MemberAccess":
                obj = callee.child("object")
                member = callee.field("member")
                if obj is not None and str(obj.field("name")) == "ta" and member in DERIVED_BUILTIN_SERIES:
                    # ta.hlc3, ta.hl2, etc. → use _RuntimeDerivedSeries for proper lookback
                    series_fn = f"{member}_series"
                    self.ctx.imports.require_from("pinelib.ta", series_fn)
                    return f"{series_fn}({runtime_expr})"
            # Non-derived builtin Call (e.g. ta.wma(close, 10)) used as source arg:
            # materialize into a temp Series so the caller receives Series, not scalar.
            expr_str = self.translate_expression(node, runtime_expr=runtime_expr)
            self._temp_series_index += 1
            temp_name = f"__tmp_{self._temp_series_index}"
            temp_ident = f"self.{temp_name}"
            # Declare the temp series inline; it persists on self across bars.
            self.emitter.line(f"if not hasattr(self, '{temp_name}'): self.{temp_name} = self.rt.series('{temp_name}', dtype='float')")
            self.emitter.line(f"{temp_ident}.set_current({expr_str})")
            return temp_ident
        if node.kind == "Identifier":
            name = str(node.field("name"))
            if name in BUILTIN_SERIES:
                return f"{runtime_expr}.{name}"
            if name in DERIVED_BUILTIN_SERIES:
                # For rolling/window TA source arguments, use _RuntimeDerivedSeries.
                # This properly implements _history lookback for rolling TA functions.
                series_fn = f"{name}_series"
                self.ctx.imports.require_from("pinelib.ta", series_fn)
                return f"{series_fn}({runtime_expr})"
            info = self.ctx.resolve_var(name)
            if info.is_series:
                return f"self.{info.py_name}"
        # BinaryExpr, UnaryExpr, or other complex expression: materialize into a temp Series.
        if node.kind in ("BinaryExpr", "UnaryExpr"):
            expr_str = self.translate_expression(node, runtime_expr=runtime_expr)
            self._temp_series_index += 1
            temp_name = f"__tmp_{self._temp_series_index}"
            temp_ident = f"self.{temp_name}"
            self.emitter.line(f"if not hasattr(self, '{temp_name}'): self.{temp_name} = self.rt.series('{temp_name}', dtype='float')")
            self.emitter.line(f"{temp_ident}.set_current({expr_str})")
            return temp_ident
        return self.translate_expression(node, runtime_expr=runtime_expr)

    def _translate_ta_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        self._bind_or_raise(name, node)
        sig = BUILTIN_SIGNATURES[name]
        # Use binder alias (e.g. "ta_range" for "ta.range")
        function_name = sig.builtin.split(".", 1)[1] if sig.builtin.startswith("ta.") else sig.builtin
        canonical_name = name.split(".", 1)[1] if name.startswith("ta.") else function_name
        import_name = self.ctx.imports.require_from("pinelib.ta", function_name)
        parameter_names = {param.name for param in BUILTIN_SIGNATURES[name].parameters}
        history_source_functions = {"crossover", "crossunder", "cross", "rising", "falling", "cum", "range", "cmo", "tsi", "cci", "mfi", "highestbars", "lowestbars", "highest", "lowest", "stdev", "variance", "dev", "change", "pivothigh", "pivotlow", "correlation", "wma", "swma", "vwma", "stoch", "mom", "roc", "alma", "linreg"}
        arguments = []
        ordered_arguments = self._ordered_call_arguments(name, node)
        for index, (arg_name, arg) in enumerate(ordered_arguments):
            parameter_name = arg_name
            if parameter_name is None and index < len(sig.parameters):
                parameter_name = sig.parameters[index].name
            # Check if arg is a DERIVED_BUILTIN_SERIES identifier or ta.* call
            is_derived_series_arg = False
            if arg.kind == "Identifier":
                is_derived_series_arg = str(arg.field("name")) in DERIVED_BUILTIN_SERIES
            elif arg.kind == "Call":
                callee = arg.child("callee")
                if callee is not None and callee.kind == "MemberAccess":
                    obj = callee.child("object")
                    member = callee.field("member")
                    is_derived_series_arg = (
                        obj is not None
                        and str(obj.field("name")) == "ta"
                        and member in DERIVED_BUILTIN_SERIES
                    )
            is_source_param = parameter_name in {"source", "source1", "source2", "high", "low", "open", "series"}
            # Use _translate_series_source_argument for rolling functions' source args,
            # OR when the arg itself is a DERIVED_BUILTIN_SERIES (hl2/hlc3/etc)
            # used as any function's source param,
            # OR for barssince/valuewhen condition/source args (need Series for history search)
            needs_series_arg = (
                (canonical_name in history_source_functions or is_derived_series_arg) and is_source_param
            ) or (
                canonical_name in {"barssince", "valuewhen"} and parameter_name in {"condition", "source"}
            )
            if needs_series_arg:
                rendered = self._translate_series_source_argument(arg, runtime_expr=runtime_expr)
            else:
                rendered = self.translate_expression(arg, runtime_expr=runtime_expr)
            arguments.append(rendered if arg_name is None or arg_name in parameter_names else f"{arg_name}={rendered}")
        if function_name == "dmi":
            arguments = [
                f"{runtime_expr}.high.current",
                f"{runtime_expr}.low.current",
                f"{runtime_expr}.close.current",
                *arguments,
            ]
        elif function_name == "sar":
            arguments = [
                f"{runtime_expr}.high.current",
                f"{runtime_expr}.low.current",
                *arguments,
            ]
        elif function_name == "tr":
            arguments = []
        if canonical_name in STATEFUL_TA_FUNCTIONS:
            state_id = state_id_for_call(self.ctx, node, canonical_name)
            arguments.extend([f"runtime={runtime_expr}", f'state_id="{state_id}"'])
        self.ctx.coverage.builtin(name)
        return f"{import_name}({', '.join(arguments)})"

    def _translate_math_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        self._bind_or_raise(name, node)
        function_name = name.split(".", 1)[1]
        import_name = self.ctx.imports.require_from("pinelib.math", function_name)
        parameter_names = {param.name for param in BUILTIN_SIGNATURES[name].parameters}
        arguments = [
            self.translate_expression(arg, runtime_expr=runtime_expr)
            if arg_name is None or arg_name in parameter_names
            else f"{arg_name}={self.translate_expression(arg, runtime_expr=runtime_expr)}"
            for arg_name, arg in self._ordered_call_arguments(name, node)
        ]
        self.ctx.coverage.builtin(name)
        return f"{import_name}({', '.join(arguments)})"

    def _translate_str_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        self._bind_or_raise(name, node)
        self.ctx.imports.require_from("pinelib", "string", alias="pine_string")
        function_name = name.split(".", 1)[1]
        parameter_names = {param.name for param in BUILTIN_SIGNATURES[name].parameters}
        arguments = [
            self.translate_expression(arg, runtime_expr=runtime_expr)
            if arg_name is None or arg_name in parameter_names
            else f"{arg_name}={self.translate_expression(arg, runtime_expr=runtime_expr)}"
            for arg_name, arg in self._ordered_call_arguments(name, node)
        ]
        self.ctx.coverage.builtin(name)
        return f"pine_string.{function_name}({', '.join(arguments)})"

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

    def _collect_declaration_metadata(self, declaration: ASTNode) -> None:
        call = declaration.child("call")
        if call is None:
            return
        allowed = DECLARATION_CONTEXT_FIELDS.get(self.ctx.mode, set())
        metadata: dict[str, Any] = {}
        for name, value_node in self._call_arguments(call):
            rendered = self.translate_expression(value_node)
            key = name or ("title" if not metadata else f"arg_{len(metadata)}")
            metadata[key] = self._literal_or_rendered(value_node, rendered)
            if name is not None and name not in allowed:
                self.ctx.add_diagnostic(
                    UNSUPPORTED_DECLARATION_ARG,
                    f"declaration argument {name!r} is not mapped for {self.ctx.mode}",
                    Severity.ERROR if self.strict else Severity.WARNING,
                    location=value_node.loc,
                )
                self.ctx.unsupported_declaration_args.append(name)
                if self.strict:
                    raise UnsupportedBuiltinError(name)
        self.ctx.strategy_metadata = metadata

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
            elif name is not None and name not in DECLARATION_CONTEXT_FIELDS.get("strategy", set()):
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

    def _contains_any_request_call(self, node: ASTNode) -> bool:
        nodes = [node, *node.descendants()]
        for descendant in nodes:
            if descendant.kind == "CallExpr":
                callee = descendant.child("callee")
                chain = member_chain(callee) if callee is not None else None
                if chain is not None and chain.startswith("request."):
                    return True
        return False

    def _diagnose_request_security_lower_tf_safety(self, expression: ASTNode) -> None:
        captured: list[str] = []
        unsafe_calls: list[str] = []
        nodes = [expression, *expression.descendants()]
        if self._contains_any_request_call(expression):
            self.ctx.add_diagnostic(
                NESTED_REQUEST_SECURITY,
                "nested request.* inside request.security_lower_tf expression is unsupported",
                Severity.ERROR,
                location=expression.loc,
            )
            raise UnsupportedBuiltinError("nested request.security_lower_tf expression")
        for descendant in nodes:
            if descendant.kind != "CallExpr":
                continue
            callee = descendant.child("callee")
            chain = member_chain(callee) if callee is not None else None
            if chain is not None and chain.startswith(LOWER_TF_PURE_CALL_PREFIXES):
                continue
            unsafe_calls.append(chain or "<dynamic-call>")
        if unsafe_calls:
            self.ctx.add_diagnostic(
                REQUEST_SECURITY_CAPTURE_UNSAFE,
                "request.security_lower_tf expression calls unsupported functions; only reviewed pure math.* calls are allowed in first-slice lowering",  # noqa: E501
                Severity.ERROR,
                location=expression.loc,
                details={"calls": sorted(set(unsafe_calls))},
            )
            raise UnsupportedBuiltinError("unsafe request.security_lower_tf call")
        for descendant in nodes:
            if descendant.kind != "Identifier":
                continue
            name = str(descendant.field("name"))
            if name in BUILTIN_SERIES or name in {"bar_index", "na"}:
                continue
            try:
                info = self.ctx.resolve_var(name)
            except ScopeResolutionError:
                continue
            if not self._is_lower_tf_safe_immutable_scalar_capture(info):
                captured.append(name)
        if captured:
            self.ctx.add_diagnostic(
                REQUEST_SECURITY_CAPTURE_UNSAFE,
                "request.security_lower_tf expression captures unsafe state; first-slice lowering only supports builtin series plus immutable scalar input captures and reviewed pure math expressions",  # noqa: E501
                Severity.ERROR,
                location=expression.loc,
                details={"captured": sorted(set(captured))},
            )
            raise UnsupportedBuiltinError("unsafe request.security_lower_tf capture")

    def _is_lower_tf_safe_immutable_scalar_capture(self, info: VariableInfo) -> bool:
        type_info = info.type_info
        if info.is_mutable or (type_info is not None and type_info.is_reference_type):
            return False
        if info.qualifier != "input" and (type_info is None or type_info.qualifier != "input"):
            return not info.is_series
        if type_info is None:
            return False
        return type_info.base_type in LOWER_TF_IMMUTABLE_SCALAR_BASE_TYPES

    def _diagnose_request_security_captures(self, expression: ASTNode) -> None:
        captured: list[str] = []
        for descendant in expression.descendants():
            if descendant.kind != "Identifier":
                continue
            name = str(descendant.field("name"))
            if name in BUILTIN_SERIES or name in {"bar_index", "na"}:
                continue
            try:
                info = self.ctx.resolve_var(name)
            except ScopeResolutionError:
                continue
            if info.is_mutable or (info.type_info is not None and info.type_info.is_reference_type):
                captured.append(name)
        if not captured:
            return
        severity = Severity.ERROR if self.strict else Severity.WARNING
        self.ctx.add_diagnostic(
            REQUEST_SECURITY_CAPTURE_UNSAFE,
            "request.security expression captures mutable or reference state; capture safety must be reviewed",  # noqa: E501
            severity,
            location=expression.loc,
            details={"captured": sorted(set(captured))},
        )
        if self.strict:
            raise UnsupportedBuiltinError("unsafe request.security capture")

    def _is_input_call(self, node: ASTNode) -> bool:
        callee = node.child("callee")
        return (
            node.kind == "CallExpr" and callee is not None and member_chain(callee) in INPUT_CALLS
        )

    def _build_input_metadata(
        self, declaration: ASTNode, initializer: ASTNode, py_name: str
    ) -> dict[str, Any]:
        callee = initializer.child("callee")
        chain = None if callee is None else member_chain(callee)
        if chain is None:
            raise UnsupportedBuiltinError("input declaration is missing a valid callee")
        info_type = chain.split(".", 1)[1]
        args = self._call_arguments(initializer)
        default_node = args[0][1]
        default_rendered = self.translate_expression(default_node)
        default_value = (
            literal_value(default_node) if default_node.kind == "Literal" else default_rendered
        )
        metadata = {
            "pine_name": declaration.field("name"),
            "py_name": py_name,
            "type": {"timeframe": "string", "session": "string", "time": "int"}.get(
                info_type, info_type
            ),
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
                "defval",
            }:
                if key == "defval":
                    continue
                metadata[key] = self._literal_or_rendered(value, self.translate_expression(value))
        public_meta = dict(metadata)
        return {
            "type": metadata["type"],
            "default_python": (
                repr(default_value) if default_node.kind == "Literal" else default_rendered
            ),
            "public": public_meta,
        }

    def _infer_dtype(self, node: ASTNode | None) -> str:
        return self._infer_type_info(node).base_type

    def _infer_type_info(self, node: ASTNode | None) -> TypeInfo:
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
                info = self.ctx.resolve_var(name)
                if info.type_info is not None:
                    if info.declaration_kind == "input":
                        return make_type_info(
                            info.type_info.base_type, "input", can_be_na=info.type_info.can_be_na
                        )
                    return info.type_info
                if info.type_ref in {"line", "label", "box", "table", "PineObjectId"}:
                    return make_type_info("PineObjectId", info.qualifier, is_series=info.is_series)
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
        if self._is_input_call(node):
            callee = node.child("callee")
            chain = None if callee is None else member_chain(callee)
            if chain is None:
                return make_type_info("object", "input")
            info_type = chain.split(".", 1)[1]
            base = {"timeframe": "string", "session": "string", "time": "int"}.get(
                info_type, info_type
            )
            return make_type_info(base, "input", can_be_na=base != "bool")
        if node.kind == "BinaryExpr":
            left = self._infer_type_info(node.child("left"))
            right = self._infer_type_info(node.child("right"))
            op = node.field("op")
            if op in {"and", "or", "==", "!=", ">", ">=", "<", "<="}:
                return make_type_info(
                    "bool", join_qualifiers(left.qualifier, right.qualifier), can_be_na=False
                )
            base = "float" if "float" in {left.base_type, right.base_type} else left.base_type
            return make_type_info(base, join_qualifiers(left.qualifier, right.qualifier))
        if node.kind == "UnaryExpr":
            return self._infer_type_info(node.child("operand"))
        if node.kind == "ConditionalExpr":
            condition = self._infer_type_info(node.child("condition"))
            if_true = self._infer_type_info(node.child("then") or node.child("if_true"))
            if_false = self._infer_type_info(node.child("else") or node.child("if_false"))
            base = (
                "float" if "float" in {if_true.base_type, if_false.base_type} else if_true.base_type
            )
            return make_type_info(
                base,
                join_qualifiers(condition.qualifier, if_true.qualifier, if_false.qualifier),
                can_be_na=base != "bool",
            )
        if node.kind == "TupleExpr":
            items = [self._infer_type_info(item) for item in node.children("elements", "items")]
            qualifier = join_qualifiers(*(item.qualifier for item in items)) if items else "const"
            return make_type_info("tuple", qualifier)
        if node.kind in {"HistoryRefExpr", "HistoryReference", "SubscriptExpr", "IndexExpr"}:
            base_info = self._infer_type_info(
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
            }:
                return make_type_info("float", "series", is_series=chain.startswith("ta."))
            if chain in {"ta.crossover", "ta.crossunder", "ta.cross", "ta.rising", "ta.falling"}:
                return make_type_info("bool", "series", is_series=True, can_be_na=False)
            if chain == "ta.barssince":
                return make_type_info("int", "series", is_series=True)
            if chain in {"ta.bb", "ta.macd"}:
                return make_type_info("tuple", "series", is_series=True)
            if chain == "request.security_lower_tf":
                return make_type_info("array", "series", is_series=True, is_history_allowed=False)
            if chain in {"input.string", "input.timeframe", "input.session"}:
                return make_type_info("string", "input", can_be_na=False)
            if chain == "input.time":
                return make_type_info("int", "input", can_be_na=False)
            if chain == "input.source":
                return make_type_info("float", "input")
            if chain in {"na"}:
                return make_type_info("bool", "simple", can_be_na=False)
            # nz and fixnan preserve the type of the first argument.
            if chain in {"nz", "fixnan"}:
                first_arg = node.child("arguments") or node.child("args")
                if first_arg is not None:
                    args = list(first_arg) if hasattr(first_arg, "__iter__") else [first_arg]
                    if args:
                        first_type = self._infer_type_info(args[0])
                        return make_type_info(
                            first_type.base_type if first_type.base_type not in {"object", "na"} else "float",
                            "series",
                            is_series=True,
                        )
                return make_type_info("float", "series", is_series=True)
            if chain in {"math.min", "math.max"}:
                arg_infos = [
                    self._infer_type_info(arg) for _, arg in self._call_arguments(node)
                ]
                qualifier = join_qualifiers(*(info.qualifier for info in arg_infos))
                base = "int" if arg_infos and all(info.base_type == "int" for info in arg_infos) else "float"
                return make_type_info(base, qualifier, is_series=qualifier == "series")
            # math.* functions return a numeric value with the strongest argument qualifier.
            if chain and chain.startswith("math."):
                arg_infos = [
                    self._infer_type_info(arg) for _, arg in self._call_arguments(node)
                ]
                qualifier = join_qualifiers(*(info.qualifier for info in arg_infos))
                return make_type_info("float", qualifier, is_series=qualifier == "series")
            # Type-cast builtins return their respective types.
            if chain == "int":
                arg_infos = [
                    self._infer_type_info(arg) for _, arg in self._call_arguments(node)
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
            if isinstance(chain, str) and chain.startswith(("array.", "map.", "matrix.")):
                return make_type_info(
                    chain.split(".", 1)[0], "series", is_series=True, is_history_allowed=False
                )
        explicit = self._type_ref_name(node)
        if explicit in REFERENCE_TYPES:
            return make_type_info(str(explicit), "series", is_series=True, is_history_allowed=False)
        return make_type_info("object", "simple")

    def _type_ref_name(self, node: ASTNode) -> str | None:
        type_ref = node.child("type_ref")
        if type_ref is None:
            return None
        name = type_ref.field("name")
        return str(name) if name is not None else None

    def _build_metadata(
        self, program: ASTProgram, *, title: str, module_name: str
    ) -> dict[str, Any]:
        declaration = {
            "kind": self.ctx.mode,
            "title": title,
            "arguments": self.ctx.strategy_metadata,
        }
        return {
            "ast2python_version": __version__,
            "generator_milestone": f"v{__version__}",
            "target_runtime_contract": RUNTIME_CONTRACT_VERSION,
            "pine_version": program.field("version", "language_version", default=6),
            "source_file": f"{module_name}.pine",
            "module_name": module_name,
            "class_name": class_name_for_mode(self.ctx.mode),
            "declaration": declaration,
            "inputs": self.ctx.input_metadata,
            "types": self.ctx.type_metadata,
            "used_builtins": sorted(self.ctx.coverage.builtins),
            "node_kind_counts": node_kind_counts(program),
            "unsupported_nodes": unsupported_node_catalog(program),
            "import_aliases": sorted(
                self.ctx.import_aliases.values(), key=lambda item: item["alias"]
            ),
            "unsupported_declaration_args": sorted(set(self.ctx.unsupported_declaration_args)),
            "parity_safe": self.parity_safe,
            "codegen_safe": not any(d.severity is Severity.ERROR for d in self.ctx.diagnostics),
            "runtime_contract_safe": self.parity_safe,
            "unsupported_features": sorted(self.unsupported_features),
            "parity_risks": self.parity_risks,
            "producer_metadata": program.field("producer_metadata"),
            "diagnostics": [item.to_dict() for item in self.ctx.diagnostics],
            "source_map_file": f"{module_name}.sourcemap.json",
        }


def translate_ast(
    program: ASTProgram | dict[str, Any],
    *,
    strict: bool = False,
    emit_source_comments: bool = True,
    module_name: str | None = None,
    allow_invalid_ast: bool = False,
    allow_contract_mismatch: bool = False,
    allow_external_library_stubs: bool = False,
    allow_unsupported_request_stubs: bool = False,
    allow_realtime_local_simulation: bool = False,
) -> TranslationResult:
    return Translator(
        strict=strict,
        emit_source_comments=emit_source_comments,
        allow_invalid_ast=allow_invalid_ast,
        allow_contract_mismatch=allow_contract_mismatch,
        allow_external_library_stubs=allow_external_library_stubs,
        allow_unsupported_request_stubs=allow_unsupported_request_stubs,
        allow_realtime_local_simulation=allow_realtime_local_simulation,
    ).translate_program(
        program,
        module_name=module_name,
    )
