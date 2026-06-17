from __future__ import annotations

from ast2python.translator_parts.shared import *  # noqa: F403,F401


class TranslatorExpressionMixin(TranslatorMixinBase):
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
        for case in switch_cases(node):
            cond = case_condition(case)
            expr = case.child("expression") or case.child("result")
            body = case_body(case)
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
            left_type = self._infer_type_info(left_node)
            right_type = self._infer_type_info(right_node)
            left = self.translate_expression(left_node, runtime_expr=runtime_expr)
            right = self.translate_expression(right_node, runtime_expr=runtime_expr)
            op = str(node.field("op"))
            # For string comparisons with == or !=, use native Python equality
            if op in ("==", "!=") and (
                left_type.base_type == "string" or right_type.base_type == "string"
            ):
                return f"({left} {op} {right})"
            # Also handle when both sides are string literals (including empty strings)
            if (
                op in ("==", "!=")
                and left == right
                and ((left.startswith("(") and left.endswith(")")) or left in ('""', "''"))
            ):
                return f"({left} {op} {right})"
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
        # group is a Pinescript built-in: group name of current input context.
        # In standalone expression (e.g. "group == group") it checks if group is set.
        # Return empty string as placeholder — no input context in generated code.
        if name == "group":
            return '""'
        if name == "hl2":
            return f"pine_div(pine_add({runtime_expr}.high.current, {runtime_expr}.low.current), 2)"
        if name == "hlc3":
            return f"pine_div(pine_add(pine_add({runtime_expr}.high.current, {runtime_expr}.low.current), {runtime_expr}.close.current), 3)"  # noqa: E501
        if name == "ohlc4":
            return f"pine_div(pine_add(pine_add(pine_add({runtime_expr}.open.current, {runtime_expr}.high.current), {runtime_expr}.low.current), {runtime_expr}.close.current), 4)"  # noqa: E501
        if name == "hlcc4":
            return f"pine_div(pine_add(pine_add(pine_add({runtime_expr}.high.current, {runtime_expr}.low.current), {runtime_expr}.close.current), {runtime_expr}.close.current), 4)"  # noqa: E501
        if name in TIME_COMPONENT_BUILTINS:
            return f"{runtime_expr}.timefunc.{name}(runtime={runtime_expr})"
        # strategy is a builtin namespace object — use self.rt.strategy for member access.
        # In strategy mode, the runtime provides self.rt.strategy which has .long/.short/etc.
        if name == "strategy":
            return f"{runtime_expr}.strategy"
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
        if chain.startswith("strategy.direction."):
            return repr(chain.rsplit(".", 1)[-1])
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
            (
                "display.",
                "currency.",
                "location.",
                "shape.",
                "size.",
                "position.",
                "plot.style_",
                "format.",
                "alert.",
            )
        ):
            return repr(chain)
        if chain.startswith("extend."):
            # Strip prefix: extend.none -> "none", extend.right -> "right"
            return repr(chain.split(".", 1)[1])
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
            # ta.atr20/30/50 are Pine built-in shorthands for ta.atr(20/30/50)
            if chain in ATR_SHORTHANDS:
                period = ATR_SHORTHANDS[chain]
                self.ctx.imports.require_from("pinelib.ta", "atr")
                state_id = state_id_for_call(self.ctx, node, f"atr_{period}")
                return f'atr({period}, runtime={runtime_expr}, state_id={state_id_py_expr(self.ctx, state_id)})'
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
            if name in TIME_COMPONENT_BUILTINS:
                return f'{runtime_expr}.expr_history({runtime_expr}.timefunc.{name}(runtime={runtime_expr}), {offset}, state_id={state_id_py_expr(self.ctx, state_id_for_call(self.ctx, node, name + "_history"))})'
            # Handle derived builtin series with history (e.g. hl2[1], hlc3[2])
            if name == "hl2":
                return f"pine_div(pine_add({runtime_expr}.high[{offset}], {runtime_expr}.low[{offset}]), 2)"
            if name == "hlc3":
                return f"pine_div(pine_add(pine_add({runtime_expr}.high[{offset}], {runtime_expr}.low[{offset}]), {runtime_expr}.close[{offset}]), 3)"
            if name == "ohlc4":
                return f"pine_div(pine_add(pine_add(pine_add({runtime_expr}.open[{offset}], {runtime_expr}.high[{offset}]), {runtime_expr}.low[{offset}]), {runtime_expr}.close[{offset}]), 4)"
            if name == "hlcc4":
                return f"pine_div(pine_add(pine_add(pine_add({runtime_expr}.high[{offset}], {runtime_expr}.low[{offset}]), {runtime_expr}.close[{offset}]), {runtime_expr}.close[{offset}]), 4)"
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
            state_id = f"{info.scope_id}_{info.py_name}_history"
            return f'{runtime_expr}.expr_history({rendered}, {offset}, state_id={state_id_py_expr(self.ctx, state_id)})'
        rendered = self.translate_expression(base, runtime_expr=runtime_expr)
        state_id = state_id_for_call(self.ctx, node, "expr_history")
        return f'{runtime_expr}.expr_history({rendered}, {offset}, state_id={state_id_py_expr(self.ctx, state_id)})'

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
