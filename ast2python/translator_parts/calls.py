from __future__ import annotations

from ast2python.translator_parts.shared import *  # noqa: F403,F401


class TranslatorCallMixin(TranslatorMixinBase):
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

        return dispatch_call(
            self,
            callee_chain,
            node,
            callee,
            runtime_expr=runtime_expr,
            exact_handlers=CALL_EXACT,
            prefix_handlers=CALL_PREFIX,
        )

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
        for index, (arg_name, arg) in enumerate(arguments):
            if name == "fixnan" and index == 0 and first_type.qualifier == "series":
                value = self._translate_series_source_argument(arg, runtime_expr=runtime_expr)
            else:
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
                f"state_id={state_id_py_expr(self.ctx, state_id)}",
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
        if expression.kind == "Identifier":
            expression_name = str(expression.field("name"))
            if expression_name in BUILTIN_SERIES:
                kwargs.append(f'expression_hint="{expression_name}"')
        kwargs.extend(
            [
                f"runtime={runtime_expr}",
                f"state_id={state_id_py_expr(self.ctx, state_id)}",
            ]
        )
        self.ctx.coverage.builtin("request.security_lower_tf")
        return f"request_security_lower_tf({', '.join(call_args + kwargs)})"

    def _translate_request_footprint(self, node: ASTNode, *, runtime_expr: str) -> str:
        self._bind_or_raise("request.footprint", node)
        call_args = [
            self.translate_expression(arg, runtime_expr=runtime_expr)
            for _, arg in self._call_arguments(node)
        ]
        state_id = state_id_for_call(self.ctx, node, "footprint")
        call_args.extend([f"runtime={runtime_expr}", f"state_id={state_id_py_expr(self.ctx, state_id)}"])
        self.ctx.coverage.builtin("request.footprint")
        self.ctx.imports.require_from("pinelib.request", "footprint", alias="request_footprint")
        return f"request_footprint({', '.join(call_args)})"

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
        return self.alert_emitter.translate_alert_call(name, node)

    def _translate_color_new(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        self._bind_or_raise(name, node)
        self.ctx.imports.require_from("pinelib", "color", alias="pine_color")
        pieces = []
        for arg_name, arg in self._ordered_call_arguments(name, node):
            rendered = self.translate_expression(arg, runtime_expr=runtime_expr)
            pieces.append(rendered if arg_name is None else f"{arg_name}={rendered}")
        self.ctx.coverage.builtin(name)
        return f"pine_color.new({', '.join(pieces)})"

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
        # Handle array.new_float, array.new_int, array.new_bool, array.new_string, array.new_color
        if namespace == "array" and method in (
            "new_float",
            "new_int",
            "new_bool",
            "new_string",
            "new_color",
        ):
            return f"PineArray.{method}({', '.join(args)})"
        if namespace == "map" and method == "new":
            return "PineMap()"
        if namespace == "matrix" and method == "new":
            return f"PineMatrix({', '.join(args)})"
        # matrix.rows / matrix.cols / matrix.columns — access as property, not method call
        if namespace == "matrix" and method in ("rows", "cols", "columns"):
            return f"{args[0]}.{method}"
        if (
            method in {"push", "set", "put", "remove", "shift", "avg", "sum", "min", "max", "sort"}
            and args
        ):
            return f"{args[0]}.{method}({', '.join(args[1:])})"
        if method in {"get", "size", "copy"} and args:
            if method == "size":
                return f"len({args[0]})"
            return f"{args[0]}.{method}({', '.join(args[1:])})"
        return f"{class_name}.{method}({', '.join(args)})"

    def _translate_strategy_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        # Handle strategy.closedtrades.xxx(index) -> self.ctx.closedtrades_xxx(index)
        if name.startswith("strategy.closedtrades.") or name.startswith("strategy.opentrades."):
            parts = name.split(".")
            ns = parts[1]  # "closedtrades" or "opentrades"
            method = parts[2]  # e.g. "entry_price"
            args = [
                self.translate_expression(arg, runtime_expr=runtime_expr)
                for _, arg in self._call_arguments(node)
            ]
            self.ctx.coverage.builtin(name)
            return f"self.ctx.{ns}_{method}({', '.join(args)})"
        # Handle strategy.risk.xxx -> self.ctx.risk_xxx(...)
        if name.startswith("strategy.risk."):
            method = name.split(".", 2)[2]  # e.g. "allow_entry_in"
            args = [
                self.translate_expression(arg, runtime_expr=runtime_expr)
                for _, arg in self._call_arguments(node)
            ]
            self.ctx.coverage.builtin(name)
            return f"self.ctx.risk_{method}({', '.join(args)})"
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
        visual_statement = visual_call_from_call_chain(name)
        if visual_statement is not None:
            if self.visual_policy == "error":
                self.ctx.add_diagnostic(
                    VISUAL_CALL_FORBIDDEN,
                    f"visual call {name} is disabled by visual_policy=error",
                    Severity.ERROR,
                    location=node.loc,
                    details={"builtin": name, "visual_policy": self.visual_policy},
                )
                raise UnsupportedBuiltinError(name)
            if self.visual_policy == "drop":
                self.ctx.coverage.builtin(name)
                return "None"
        arguments = self._ordered_call_arguments(name, node)

        # Fast-path for plot(): emit direct record_plot() call
        # to avoid _visual_call function-call + conditional overhead
        if name == "plot":
            pieces = []
            title_expr = "''"
            extra_kwargs: list[str] = []
            for arg_name, arg in arguments:
                rendered = self.translate_expression(arg, runtime_expr=runtime_expr)
                if arg_name is None or arg_name in {"series", "value"}:
                    pieces.append(rendered)
                elif arg_name == "title":
                    title_expr = rendered
                else:
                    extra_kwargs.append(f"{arg_name}={rendered}")
            # If title was positional (second arg), extract it
            if len(pieces) >= 2 and title_expr == "''":
                title_expr = pieces[1]
            if extra_kwargs:
                general_pieces = [*pieces, *extra_kwargs]
                general_pieces.append(f'source_map="{node.loc.source_map if node.loc else ""}"')
                self.ctx.coverage.builtin(name)
                return f"self._visual_call({name!r}, {', '.join(general_pieces)})"
            # Emit: self.rt.plot_recorder.record_plot(
            #     bar_time=self.rt.current_bar.time,
            #     bar_index=self.rt.bar_index,
            #     value=<series>,
            #     title=<title_expr>,
            # )
            series_val = pieces[0] if pieces else "None"
            self.ctx.coverage.builtin(name)
            return (
                f"self.rt.plot_recorder.record_plot("
                f"bar_time=self.rt.current_bar.time if self.rt.current_bar else 0,"
                f"bar_index=self.rt.bar_index,"
                f"value={series_val},"
                f"title={title_expr})"
            )

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
        return self.input_emitter.translate_runtime_lookup(node)

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
        import os

        if os.environ.get("DEBUG_BIND"):
            os.makedirs("/tmp/debug_dir", exist_ok=True)
            with open("/tmp/debug_dir/bind_trace.txt", "a") as f:
                f.write(f"_bind_or_raise({name}) errors={errors!r}\n")
        if name in BUILTIN_SIGNATURES and not BUILTIN_SIGNATURES[name].codegen_supported:
            raise UnsupportedBuiltinError(name)
        raise TypeResolutionError(f"{name} semantic binding failed")

    def _ordered_call_arguments(self, name: str, node: ASTNode) -> list[tuple[str | None, ASTNode]]:
        return ordered_call_arguments(name, node)

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
                if (
                    obj is not None
                    and str(obj.field("name")) == "ta"
                    and member in DERIVED_BUILTIN_SERIES
                ):
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
            self.emitter.line(
                f"if not hasattr(self, '{temp_name}'): self.{temp_name} = self.rt.series('{temp_name}', dtype='float')"
            )
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
            if runtime_expr != "self.rt":
                return expr_str
            self._temp_series_index += 1
            temp_name = f"__tmp_{self._temp_series_index}"
            temp_ident = f"self.{temp_name}"
            self.emitter.line(
                f"if not hasattr(self, '{temp_name}'): self.{temp_name} = self.rt.series('{temp_name}', dtype='float')"
            )
            self.emitter.line(f"{temp_ident}.set_current({expr_str})")
            return temp_ident
        return self.translate_expression(node, runtime_expr=runtime_expr)

    def _translate_ta_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        self._bind_or_raise(name, node)
        sig = BUILTIN_SIGNATURES[name]
        # Use binder alias (e.g. "ta_range" for "ta.range")
        function_name = (
            sig.builtin.split(".", 1)[1] if sig.builtin.startswith("ta.") else sig.builtin
        )
        canonical_name = name.split(".", 1)[1] if name.startswith("ta.") else function_name
        import_name = self.ctx.imports.require_from("pinelib.ta", function_name)
        parameter_names = {param.name for param in BUILTIN_SIGNATURES[name].parameters}
        history_source_functions = {
            "crossover",
            "crossunder",
            "cross",
            "rising",
            "falling",
            "cum",
            "range",
            "cmo",
            "tsi",
            "cci",
            "mfi",
            "highestbars",
            "lowestbars",
            "highest",
            "lowest",
            "stdev",
            "variance",
            "dev",
            "change",
            "pivothigh",
            "pivotlow",
            "correlation",
            "wma",
            "swma",
            "vwma",
            "stoch",
            "mom",
            "roc",
            "alma",
            "linreg",
        }
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
            is_source_param = parameter_name in {
                "source",
                "source1",
                "source2",
                "high",
                "low",
                "open",
                "series",
            }
            # Use _translate_series_source_argument for rolling functions' source args,
            # OR when the arg itself is a DERIVED_BUILTIN_SERIES (hl2/hlc3/etc)
            # used as any function's source param,
            # OR for barssince/valuewhen condition/source args (need Series for history search)
            needs_series_arg = (
                (canonical_name in history_source_functions or is_derived_series_arg)
                and is_source_param
            ) or (
                canonical_name in {"barssince", "valuewhen"}
                and parameter_name in {"condition", "source"}
            )
            if needs_series_arg:
                rendered = self._translate_series_source_argument(arg, runtime_expr=runtime_expr)
            else:
                rendered = self.translate_expression(arg, runtime_expr=runtime_expr)
            arguments.append(
                rendered
                if arg_name is None or arg_name in parameter_names
                else f"{arg_name}={rendered}"
            )
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
            arguments.extend([f"runtime={runtime_expr}", f"state_id={state_id_py_expr(self.ctx, state_id)}"])
            if getattr(self, "_lazy_branch_depth", 0) > 0 and canonical_name in {"highest", "lowest"}:
                arguments.append("tv_lazy_state=True")
        self.ctx.coverage.builtin(name)
        return f"{import_name}({', '.join(arguments)})"

    def _translate_math_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str:
        self._bind_or_raise(name, node)
        function_name = name.split(".", 1)[1]
        import_name = self.ctx.imports.require_from("pinelib.math", function_name)
        parameter_names = {param.name for param in BUILTIN_SIGNATURES[name].parameters}
        arguments = [
            (
                self.translate_expression(arg, runtime_expr=runtime_expr)
                if arg_name is None or arg_name in parameter_names
                else f"{arg_name}={self.translate_expression(arg, runtime_expr=runtime_expr)}"
            )
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
            (
                self.translate_expression(arg, runtime_expr=runtime_expr)
                if arg_name is None or arg_name in parameter_names
                else f"{arg_name}={self.translate_expression(arg, runtime_expr=runtime_expr)}"
            )
            for arg_name, arg in self._ordered_call_arguments(name, node)
        ]
        self.ctx.coverage.builtin(name)
        return f"pine_string.{function_name}({', '.join(arguments)})"

    def _call_arguments(self, node: ASTNode) -> list[tuple[str | None, ASTNode]]:
        return call_arguments(node)
