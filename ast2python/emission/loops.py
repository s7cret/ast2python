"""Loop values preserve the last completed return expression across break/continue.

No loop body is moved into an eagerly executed temporary expression. Python loop
control stays in its lexical loop; nested loops own independent accumulators.
"""

from __future__ import annotations

from ast2python.errors import BundleInvariantError

LOOPS = {"ForRangeStructure", "ForInStructure", "WhileStructure"}


class LoopEmissionMixin:
    def _capture_nonlocals(self, key):
        subtree = set(self._subtree(key))
        nonlocals = set()
        for child in subtree:
            if self._attrs(child).get("ast_kind") != "Reassignment":
                continue
            targets = self._role(child, "target")
            if targets and self._attrs(targets[0]).get("ast_kind") == "Identifier":
                target = targets[0]
                name = self._lookup_local(self._scope(target), self._fields(target).get("name"))
                declaration = self.declarations_by_py.get(name)
                if declaration and declaration[1] not in subtree:
                    nonlocals.add(name)
        if nonlocals:
            self.writer.line("nonlocal " + ", ".join(sorted(nonlocals)))

    def _loop_expression(self, key):
        name = self._safe("value", "loop_value", key)
        value = self._safe("result", "loop_result", key)
        self.writer.line(f"def {name}():")
        self.writer.indent()
        self._capture_nonlocals(key)
        self.writer.line(f"{value} = {self._default_block_value(key)}")
        self._emit_loop(key, result=value)
        self.writer.line(f"return {value}")
        self.writer.dedent()
        return f"{name}()"

    def _emit_loop(self, key, *, result=None):
        self._require_language_contract("compiler.loop_values.v1")
        kind = self._attrs(key)["ast_kind"]
        body = self._role(key, "body")[0]
        if kind == "ForRangeStructure":
            fields = self._fields(key)
            variable = fields["variable"]
            pyname = self.local_names[("scope:loop:" + self._node(key).source.node_id, variable)]
            start, end, step = (
                self._role(key, "start"),
                self._role(key, "end"),
                self._role(key, "step"),
            )
            iterator = self._runtime_operation(
                self._node(key).opcode,
                self._expr(start[0]),
                "lambda: " + self._expr(end[0]),
                self._expr(step[0]) if step else "1",
            )
            self.writer.line(f"for {pyname} in {iterator}:", ir_ids=(key,), origin="PINE")
        elif kind == "ForInStructure":
            target = self._role(key, "target")[0]
            names = self._fields(target)["names"]
            py = [
                self.local_names[("scope:loop:" + self._node(key).source.node_id, name)]
                for name in names
            ]
            iterable = self._expr(self._role(key, "iterable")[0])
            typ = self._node(self._role(key, "iterable")[0]).result_type
            if typ is None or not typ.base.startswith("array<"):
                raise BundleInvariantError(
                    "A2P_FOR_IN_TYPE", "compiled iteration requires an exact array type"
                )
            self.writer.line(
                f"for {', '.join(py)} in self.runtime.iter_array_v1({iterable}, indexed={len(names) == 2!r}):",
                ir_ids=(key,),
                origin="PINE",
            )
        elif kind == "WhileStructure":
            # Evaluate the condition at each iteration, including a condition that
            # needs an emitted block helper. Bound each actual loop iteration.
            self.writer.line("while True:", ir_ids=(key,), origin="PINE")
        else:
            raise BundleInvariantError("A2P_LOOP_KIND", "unknown loop kind")
        self.writer.indent()
        if kind == "WhileStructure":
            condition = self._condition(self._role(key, "condition")[0])
            self.writer.line(f"if not ({condition}):")
            self.writer.indent()
            self.writer.line("break")
            self.writer.dedent()
        self.writer.line("self.runtime.consume_loop_iteration_v1()")
        if result is None:
            self._emit_block(body)
        else:
            self._emit_result_block(body, result)
        self.writer.dedent()

    def _emit_result_block(self, key, result):
        if self._attrs(key).get("ast_kind") != "Block":
            self.writer.line(
                f"{result} = {self._expr(key)}", ir_ids=self._subtree(key), origin="PINE"
            )
            return
        statements = list(self._role(key, "statements"))
        if not statements:
            self.writer.line("pass")
            return
        for statement in statements[:-1]:
            self._emit_statement(statement)
        last = statements[-1]
        kind = self._attrs(last).get("ast_kind")
        if kind == "ExpressionStatement":
            self.writer.line(
                f"{result} = {self._expr(self._role(last, 'expression')[0])}",
                ir_ids=self._subtree(last),
                origin="PINE",
            )
        elif kind in {"VarDeclaration", "Reassignment"}:
            self._emit_statement(last)
            name = (
                self._lookup_local(self._scope(last), self._fields(last)["name"])
                if kind == "VarDeclaration"
                else self._identifier(self._role(last, "target")[0])
            )
            self.writer.line(f"{result} = {name}", ir_ids=(last,), origin="PINE")
        elif kind == "IfStructure":
            arms = [(self._role(last, "condition")[0], self._role(last, "then_block")[0])]
            arms += [
                (self._role(br, "condition")[0], self._role(br, "block")[0])
                for br in self._role(last, "else_if_branches")
            ]
            other = self._role(last, "else_block")
            self._emit_result_arms(arms, other[0] if other else None, result, last)
        elif kind == "SwitchStructure":
            selectors = self._role(last, "expression")
            selector = self._safe("selector", "loop_switch", last) if selectors else None
            if selector:
                self.writer.line(f"{selector} = {self._expr(selectors[0])}")
            arms, other = [], None
            for case in self._role(last, "cases"):
                condition = self._role(case, "condition")
                if condition:
                    arms.append((condition[0], self._role(case, "body")[0]))
                else:
                    other = self._role(case, "body")[0]
            self._emit_result_arms(arms, other, result, last, selector=selector)
        elif kind in LOOPS:
            self.writer.line(
                f"{result} = {self._loop_expression(last)}", ir_ids=(last,), origin="PINE"
            )
        else:
            # break/continue deliberately bypass the assignment, retaining the
            # previous completed iteration's value (or initial NA).
            self._emit_statement(last)

    def _emit_result_arms(self, arms, other, result, key, selector=None):
        if not arms:
            if other is not None:
                self._emit_result_block(other, result)
            else:
                self.writer.line(f"{result} = {self._default_block_value(key)}")
            return
        condition, body = arms[0]
        test = (
            f"self.runtime.condition_v1(self.runtime.op_operator_binary('==', {selector}, {self._expr(condition)}))"
            if selector
            else self._condition(condition)
        )
        self.writer.line(f"if {test}:")
        self.writer.indent()
        self._emit_result_block(body, result)
        self.writer.dedent()
        self.writer.line("else:")
        self.writer.indent()
        self._emit_result_arms(arms[1:], other, result, key, selector)
        self.writer.dedent()
