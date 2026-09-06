"""Lexical scalar execution and block values emitted from checked IR.

Calls are keyed by written callsites, not loop iterations or Python object IDs.
Language state remains in PineLib's transaction/series/slot machinery.
"""

from __future__ import annotations

from ast2python.errors import BundleInvariantError

SCALARS = {"bool", "color", "float", "int", "string"}


class LanguageEmissionMixin:
    def _prepare_names(self):
        self.current_function = None
        self.scope_parents = {"scope:global": None}
        self.declarations_by_py = {}
        self.function_declarations = {}
        if not self.exact_pinelib:
            self._prepare_legacy_names()
            return
        for key in self.plan.ordered_ir_ids:
            scope = self._scope(key)
            for child in self._node(key).child_ir_ids:
                nested = self._scope(child)
                if nested != scope:
                    previous = self.scope_parents.setdefault(nested, scope)
                    if previous != scope:
                        raise BundleInvariantError(
                            "A2P_LEXICAL_SCOPE", "inconsistent scope ancestry"
                        )
        for key in self.plan.ordered_ir_ids:
            attrs, fields, scope = self._attrs(key), self._fields(key), self._scope(key)
            kind, name = attrs.get("ast_kind"), fields.get("name")
            if kind in {"VarDeclaration", "Parameter", "TupleTarget"} and isinstance(name, str):
                pyname = self._safe(name, "var", self._node(key).source.node_id)
                self.local_names[(scope, name)] = pyname
                self.names_by_source[self._node(key).source.node_id] = pyname
                self.declarations_by_py[pyname] = (scope, key)
                if kind in {"VarDeclaration", "Parameter"}:
                    dtype = self._declaration_type(key)
                    if dtype in SCALARS:
                        sid = (
                            "series:" if scope == "scope:global" else "local-series:"
                        ) + self._node(key).source.node_id
                        self.series_ids[(scope, name)] = sid
                        self.scalar_declarations[pyname] = (
                            sid,
                            str(fields.get("mode") or "default"),
                            dtype,
                        )
            elif kind == "ForRangeStructure":
                variable = fields.get("variable")
                if isinstance(variable, str):
                    self.local_names[("scope:loop:" + self._node(key).source.node_id, variable)] = (
                        self._safe(variable, "loop", key)
                    )
            elif kind in {"FunctionDeclaration", "MethodDeclaration"} and isinstance(name, str):
                self.functions_by_name[name] = self._safe(
                    name, "udf", self._node(key).source.node_id
                )
                self.function_ir_ids.add(key)
                self.function_declarations[name] = key

    def _scope(self, key):
        return str(self._attrs(key).get("scope_id") or "scope:global")

    def _lookup_local(self, scope, name):
        if not self.exact_pinelib:
            return self._legacy_lookup(scope, name)
        visited = set()
        while scope is not None:
            if scope in visited:
                raise BundleInvariantError("A2P_LEXICAL_SCOPE", "cyclic scope ancestry")
            visited.add(scope)
            value = self.local_names.get((scope, name))
            if value is not None:
                return value
            scope = self.scope_parents.get(scope)
        return None

    def _declaration_type(self, key):
        declared = self._role(key, "type_ref")
        if declared:
            return str(self._fields(declared[0]).get("name"))
        initializer = self._role(key, "initializer")
        typ = self._node(initializer[0]).result_type if initializer else None
        return typ.base if typ is not None else "object"

    def _series_argument(self, sid):
        return (
            f"self.runtime.scoped_id_v1({sid!r}, local=True)"
            if sid.startswith("local-series:")
            else repr(sid)
        )

    def _history_policy(self, sid):
        return "on_evaluation" if sid.startswith("local-series:") else "each_bar"

    def _series_identity(self, key):
        if not self.exact_pinelib:
            return self._legacy_series_identity(key)
        attrs, fields = self._attrs(key), self._fields(key)
        if attrs.get("ast_kind") != "Identifier":
            return None
        name = str(fields.get("name") or "")
        local = self._lookup_local(self._scope(key), name)
        if local in self.scalar_declarations:
            return self.scalar_declarations[local][0]
        if attrs.get("symbol_id") == "pine:variable:" + name and name in {
            "open",
            "high",
            "low",
            "close",
            "volume",
            "time",
            "time_close",
            "bar_index",
            "last_bar_index",
        }:
            return name
        return None

    def _condition(self, key):
        value = self._expr(key)
        return f"self.runtime.condition_v1({value})" if self.exact_pinelib else f"bool({value})"

    def _default_block_value(self, key):
        typ = self._node(key).result_type
        if typ is not None:
            is_bool = typ.base == "bool"
        else:
            # Statements used as the last expression of a UDF have structural
            # facts. Consult the typed return expressions, not a Python guess.
            ends = []

            def inspect(node):
                kind = self._attrs(node).get("ast_kind")
                if kind == "Block":
                    items = self._role(node, "statements")
                    if items:
                        inspect(items[-1])
                elif kind == "IfStructure":
                    for role in ("then_block", "else_block"):
                        for child in self._role(node, role):
                            inspect(child)
                    for branch in self._role(node, "else_if_branches"):
                        for child in self._role(branch, "block"):
                            inspect(child)
                elif kind == "SwitchStructure":
                    for case in self._role(node, "cases"):
                        for child in self._role(case, "body"):
                            inspect(child)
                elif kind == "ExpressionStatement":
                    for child in self._role(node, "expression"):
                        inspect(child)
                else:
                    node_type = self._node(node).result_type
                    ends.append(node_type.base if node_type else "unknown")

            inspect(key)
            is_bool = bool(ends) and all(t == "bool" for t in ends)
        return (
            "False"
            if self.plan.pine_version >= 6 and is_bool
            else "_PineLibNA"
            if self.exact_pinelib
            else "None"
        )

    def _value_block(self, key):
        if self._attrs(key).get("ast_kind") == "Block":
            self._emit_block(key, return_last=True)
        else:
            self.writer.line(f"return {self._expr(key)}", ir_ids=self._subtree(key), origin="PINE")

    def _block_expression(self, key):
        name = self._safe("value", "block_value", key)
        self.writer.line(f"def {name}():")
        self.writer.indent()
        subtree = set(self._subtree(key))
        nonlocals = set()
        for child in subtree:
            if self._attrs(child).get("ast_kind") != "Reassignment":
                continue
            targets = self._role(child, "target")
            if targets and self._attrs(targets[0]).get("ast_kind") == "Identifier":
                target = targets[0]
                pyname = self._lookup_local(self._scope(target), self._fields(target).get("name"))
                decl = self.declarations_by_py.get(pyname)
                if decl and decl[1] not in subtree:
                    nonlocals.add(pyname)
        if nonlocals:
            self.writer.line("nonlocal " + ", ".join(sorted(nonlocals)))
        if self._attrs(key).get("ast_kind") == "IfStructure":
            arms = [(self._role(key, "condition")[0], self._role(key, "then_block")[0])]
            arms += [
                (self._role(branch, "condition")[0], self._role(branch, "block")[0])
                for branch in self._role(key, "else_if_branches")
            ]
            other = self._role(key, "else_block")
            self._emit_if_chain(arms, other[0] if other else None, value=True)
        else:
            selectors = self._role(key, "expression")
            selector = self._safe("selector", "local", key)
            if selectors:
                self.writer.line(f"{selector} = {self._expr(selectors[0])}")
            cases = self._role(key, "cases")
            arms, default = [], None
            for case in cases:
                conditions = self._role(case, "condition")
                if not conditions:
                    if default is not None:
                        raise BundleInvariantError(
                            "A2P_EMIT_SWITCH_CASE", "duplicate switch default"
                        )
                    default = self._role(case, "body")[0]
                else:
                    if default is not None:
                        raise BundleInvariantError(
                            "A2P_EMIT_SWITCH_CASE", "switch default must be last"
                        )
                    arms.append((conditions[0], self._role(case, "body")[0]))
            self._emit_if_chain(arms, default, value=True, selector=selector if selectors else None)
        self.writer.line("return " + self._default_block_value(key))
        self.writer.dedent()
        return f"{name}()"

    def _emit_if_chain(self, arms, otherwise, *, value, selector=None):
        # Nested else/if preserves lazy condition evaluation even when an
        # expression requires a checked block-value helper declaration.
        if not arms:
            if otherwise is not None:
                self._value_block(otherwise) if value else self._emit_block(otherwise)
            return
        condition, block = arms[0]
        if selector is not None:
            right = self._expr(condition)
            expression = (
                f"self.runtime.condition_v1(self.runtime.op_operator_binary('==', {selector}, {right}))"
                if self.exact_pinelib
                else f"{selector} == {right}"
            )
        else:
            expression = self._condition(condition)
        self.writer.line(f"if {expression}:", ir_ids=(condition,), origin="PINE")
        self.writer.indent()
        self._value_block(block) if value else self._emit_block(block)
        self.writer.dedent()
        if len(arms) > 1 or otherwise is not None:
            self.writer.line("else:")
            self.writer.indent()
            self._emit_if_chain(arms[1:], otherwise, value=value, selector=selector)
            self.writer.dedent()
