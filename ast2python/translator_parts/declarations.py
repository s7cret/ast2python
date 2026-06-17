from __future__ import annotations

from ast2python.translator_parts.shared import *  # noqa: F403,F401


class TranslatorDeclarationMixin(TranslatorMixinBase):
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
        # UDFs that may contain stateful TA calls (ta.ema, ta.lowest, etc.)
        # get an extra _cs_id parameter so each call site gets isolated state.
        py_params_with_cs = list(py_params) + ["_cs_id=\"\""]
        self.emitter.line(
            f"def {name}(self{', ' if py_params_with_cs else ''}{', '.join(py_params_with_cs)}):",
            loc=node.loc,
            source=node.source,
        )
        self.emitter.indent()
        self.ctx.enter_scope("function")
        prev_function = self.ctx.current_function
        self.ctx.current_function = name
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
                is_last_statement = index == len(statements) - 1
                if is_last_statement and statement.kind == "ExpressionStatement":
                    expr = statement.child("expression")
                    self.emitter.source_comment(statement.loc, statement.source)
                    self.emitter.line(
                        (
                            f"return {self.translate_expression(expr)}"
                            if expr is not None
                            else "return None"
                        ),
                        loc=statement.loc,
                        source=statement.source,
                    )
                elif is_last_statement and statement.kind == "VarDeclaration":
                    self._emit_statement(statement)
                    var_name = str(statement.field("name"))
                    try:
                        info = self.ctx.resolve_var(var_name)
                    except ScopeResolutionError:
                        self.emitter.line("return None", loc=statement.loc, source=statement.source)
                    else:
                        self.emitter.line(
                            f"return {info.py_name}",
                            loc=statement.loc,
                            source=statement.source,
                        )
                else:
                    self._emit_statement(statement)
        self.ctx.exit_scope()
        self.ctx.current_function = prev_function
        self.emitter.dedent()

    def _python_type_name(self, pine_type: str | None) -> str:
        return {"int": "int", "float": "float", "bool": "bool", "string": "str", "str": "str"}.get(
            str(pine_type), "object"
        )

    def _default_for_type(self, pine_type: str | None) -> str:
        return {"int": "0", "float": "na", "bool": "False", "string": "''", "str": "''"}.get(
            str(pine_type), "na"
        )
