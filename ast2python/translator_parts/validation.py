from __future__ import annotations

from ast2python.translator_parts.shared import *  # noqa: F403,F401


class TranslatorValidationMixin(TranslatorMixinBase):
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
        frontend_diagnostics: list[dict[str, Any]] = []
        ignored_visual_diagnostics: list[dict[str, Any]] = []
        for item in program.field("diagnostics", default=[]) or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("severity", "")).lower() not in {"error", "fatal"}:
                continue
            visual_builtin = frontend_diagnostic_visual_call(item)
            if visual_builtin is not None and self.visual_policy in {"drop", "record"}:
                ignored_visual_diagnostics.append({**item, "visual_builtin": visual_builtin})
                continue
            frontend_diagnostics.append(item)
        if ignored_visual_diagnostics:
            self.ctx.add_diagnostic(
                VISUAL_FRONTEND_DIAGNOSTIC_IGNORED,
                "Pine2AST visual runtime-contract diagnostics were accepted under the selected visual policy",
                Severity.WARNING,
                details={
                    "visual_policy": self.visual_policy,
                    "frontend_diagnostics": ignored_visual_diagnostics,
                },
            )
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
        metadata_contract_ok = (
            isinstance(metadata, dict)
            and ast_contract_is_current(contract)
            and runtime_contract_is_compatible(runtime_contract)
        )
        if not metadata_contract_ok:
            self.ctx.add_diagnostic(
                CONTRACT_VERSION_MISMATCH,
                "Pine2AST producer metadata missing or mismatched contract/runtime profile",
                Severity.ERROR,
                details={
                    "expected_contract": AST_CONTRACT_VERSION,
                    "actual_contract": contract,
                    "expected_runtime_contract": expected,
                    "actual_runtime_contract": runtime_contract,
                    "metadata": metadata,
                },
            )
            if not self.allow_contract_mismatch:
                raise ValidationError(
                    "Pine2AST producer metadata missing/mismatched runtime contract"
                )
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
                self.parity_risks.append(
                    "allow_invalid_ast override used with non-pass frontend gates"
                )

    def _enforce_realtime_boundary(self, declaration: ASTNode) -> None:
        if self.ctx.mode != "strategy" or not self._strategy_calc_on_every_tick_enabled(
            declaration
        ):
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
            if node.kind == "VarDeclaration"
            and str(node.field("mode", default="")).lower() == "varip"
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
