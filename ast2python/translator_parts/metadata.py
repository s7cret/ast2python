from __future__ import annotations

from ast2python.translator_parts.shared import *  # noqa: F403,F401


class TranslatorMetadataMixin(TranslatorMixinBase):
    def _extract_declaration_title(self, declaration: ASTNode) -> str:
        return extract_declaration_title(self, declaration)

    def _collect_declaration_metadata(self, declaration: ASTNode) -> None:
        collect_declaration_metadata(self, declaration, DECLARATION_CONTEXT_FIELDS)

    def _strategy_context_kwargs(self, declaration: ASTNode) -> list[tuple[str, str]]:
        return strategy_context_kwargs(
            self,
            declaration,
            STRATEGY_CONTEXT_FIELDS,
            DECLARATION_CONTEXT_FIELDS,
        )

    def _literal_or_rendered(self, node: ASTNode, rendered: str) -> Any:
        return literal_or_rendered(node, rendered)

    def _contains_request_call(self, node: ASTNode) -> bool:
        return contains_request_call(node)

    def _contains_any_request_call(self, node: ASTNode) -> bool:
        return contains_any_request_call(node)

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
        return self.input_emitter.is_input_call(node)

    def _build_input_metadata(
        self, declaration: ASTNode, initializer: ASTNode, py_name: str
    ) -> dict[str, Any]:
        return self.input_emitter.build_metadata(declaration, initializer, py_name)

    def _infer_dtype(self, node: ASTNode | None) -> str:
        return self._infer_type_info(node).base_type

    def _infer_type_info(self, node: ASTNode | None) -> TypeInfo:
        return infer_type_info(self, node)

    def _type_ref_name(self, node: ASTNode) -> str | None:
        type_ref = node.child("type_ref")
        if type_ref is None:
            return None
        name = type_ref.field("name")
        return str(name) if name is not None else None

    def _build_metadata(
        self, program: ASTProgram, *, title: str, module_name: str
    ) -> dict[str, Any]:
        return build_metadata(self, program, title=title, module_name=module_name)
