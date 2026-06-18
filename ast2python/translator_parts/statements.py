from __future__ import annotations

from ast2python.translator_parts.shared import *  # noqa: F403,F401


class TranslatorStatementMixin(TranslatorMixinBase):
    def _collect_globals(self, program: ASTProgram) -> None:
        self._var_init_emitted = set()
        collect_globals(self, program)

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
            info = self.ctx.resolve_var(name)
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
        # Variable already exists: re-infer type from initializer to handle
        # tuple-target pre-declaration (which sets wrong type before tuple unpacking)
        if initializer is not None:
            info.type_info = self._infer_type_info(initializer)
            self.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = info.type_info.to_dict()
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
        # When `var x := rhs` is a reassign (not the first init), the RHS must
        # see the previous bar's value of every series that was updated earlier
        # in the same `_process_bar` call. The default codegen emits
        # `self.<series>.current`, but that is the *just-assigned* value, not
        # the previous bar's value. Rewrite those references in the RHS to
        # `self.<series>[1]` to restore Pine's one-bar-deferred semantics.
        if (
            info.declaration_kind == "var"
            and self.ctx.current_scope.kind == "global"
            and info.pine_name in getattr(self, "_var_init_emitted", set())
        ):
            expr = self._defer_series_reads_to_previous_bar(expr)
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
            self._var_init_emitted.add(info.pine_name)
            return
        if info.declaration_kind == "varip":
            self.emitter.line(
                f'{info.py_name} = self.rt.get_varip_state("{self._varip_key(info)}", lambda: {expr})',
                loc=node.loc,
                source=node.source,
            )
        else:
            self.emitter.line(f"{info.py_name} = {expr}", loc=node.loc, source=node.source)

    def _defer_series_reads_to_previous_bar(self, expr: str) -> str:
        """Replace `self.<py_name>.current` with `self.<py_name>[1]` for every
        series variable currently declared in the active scope. Used to give
        `var := rhs` reassign the Pine one-bar-deferred semantics.
        """
        rewritten = expr
        for other in self.ctx.current_scope.variables.values():
            if not other.is_series or other.py_name == "":
                continue
            rewritten = rewritten.replace(
                f"self.{other.py_name}.current", f"self.{other.py_name}[1]"
            )
        return rewritten

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
            elif chain == "request.security":
                # request.security(sym, tf, tuple_returning_expr) — unwrap inner expr
                args = self._call_arguments(initializer)
                if len(args) >= 3:
                    expr_arg = args[2][1]
                    if expr_arg.kind == "CallExpr":
                        expr_callee = expr_arg.child("callee")
                        expr_chain = member_chain(expr_callee) if expr_callee else None
                        if expr_chain in self.TUPLE_RETURNING_BUILTINS:
                            tuple_element_types = list(self.TUPLE_RETURNING_BUILTINS[expr_chain])
                    elif expr_arg.kind == "TupleExpr":
                        # [open, high, low, close] in request.security — each is a series float
                        tuple_element_types = ["float"] * len(expr_arg.children("elements"))
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
                for i, (gs_info, _gs_dtype) in enumerate(self.global_series):
                    if gs_info is info:
                        self.global_series[i] = (info, elem_base)
                        break
            temp = f"_{info.py_name}"
            temp_names.append(temp)
            assignments.append((info, temp))
        # Check if this is a request.security call returning a tuple (na-check needed)
        initializer_callee = initializer.child("callee")
        is_req_security_tuple = (
            initializer.kind == "CallExpr"
            and initializer_callee is not None
            and member_chain(initializer_callee) == "request.security"
            and tuple_element_types is not None
        )
        rendered_expr = self.translate_expression(initializer)
        if is_req_security_tuple:
            # Guard against na: request.security can return PineNASentinel when
            # no data is available, which is not iterable and can't be unpacked.
            na_tuple_str = f"({', '.join(['na'] * len(temp_names))},)"
            self.emitter.line(f"_req_sec_result = {rendered_expr}")
            self.emitter.line("if is_na(_req_sec_result):")
            self.emitter.indent()
            self.emitter.line(f"{', '.join(temp_names)} = {na_tuple_str}")
            self.emitter.dedent()
            self.emitter.line("else:")
            self.emitter.indent()
            self.emitter.line(f"{', '.join(temp_names)} = _req_sec_result")
            self.emitter.dedent()
        else:
            self.emitter.line(
                f"{', '.join(temp_names)} = {rendered_expr}",
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
        self._enter_lazy_branch()
        try:
            if then_block.children("statements"):
                for statement in then_block.children("statements"):
                    self._emit_statement(statement)
            else:
                self.emitter.line("pass")
        finally:
            self._exit_lazy_branch()
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
            self._enter_lazy_branch()
            try:
                for statement in branch_block.children("statements"):
                    self._emit_statement(statement)
            finally:
                self._exit_lazy_branch()
            self.ctx.exit_scope()
            self.emitter.dedent()
        if else_block is not None:
            self.emitter.line("else:")
            self.emitter.indent()
            self.ctx.enter_scope("block")
            self._enter_lazy_branch()
            try:
                if else_block.children("statements"):
                    for statement in else_block.children("statements"):
                        self._emit_statement(statement)
                else:
                    self.emitter.line("pass")
            finally:
                self._exit_lazy_branch()
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
        self.alert_emitter.emit_alert_condition_statement(node)

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
        return switch_cases(node)

    def _case_condition(self, case: ASTNode) -> ASTNode | None:
        return case_condition(case)

    def _case_body(self, case: ASTNode) -> ASTNode | None:
        return case_body(case)

    def _emit_switch(self, node: ASTNode) -> None:
        subject = node.child("expression") or node.child("subject") or node.child("target")
        emitted = False
        for case in switch_cases(node):
            cond = case_condition(case)
            body = case_body(case)
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
            self._enter_lazy_branch()
            try:
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
            finally:
                self._exit_lazy_branch()
            self.emitter.dedent()
        if not emitted:
            self.emitter.line("pass", loc=node.loc, source=node.source)
