"""Dependency-sliced request methods emitted from checked IR, never Pine strings."""

from __future__ import annotations

import hashlib

from ast2python.errors import BundleInvariantError


class RequestEmissionMixin:
    def _prepare_requests(self):
        self.request_methods = {}
        declarations = {}
        mutated = set()
        for key in self.plan.ordered_ir_ids:
            attrs, fields = self._attrs(key), self._fields(key)
            if (
                attrs.get("ast_kind") == "VarDeclaration"
                and attrs.get("scope_id") == "scope:global"
            ):
                declarations[fields["name"]] = key
            if attrs.get("ast_kind") == "Reassignment":
                for target in self._role(key, "target"):
                    mutated.add(self._fields(target).get("name"))
        for key in self.plan.ordered_ir_ids:
            call = self._attrs(key).get("call")
            if not isinstance(call, dict):
                continue
            binding = self.target.call_bindings.get(
                (str(call["symbol_id"]), str(call["overload_id"]), str(call["call_form"]))
            )
            if binding is None or binding.state_model != "COMPILED_REQUEST_EXPRESSION":
                continue
            args = self.metadata.argument_nodes(key)
            expression = args.get("expression")
            if expression is None:
                self._request_error(key, "request requires an expression")
            dependencies, visiting, visited = [], set(), set()

            def visit(node, dependencies=dependencies, visiting=visiting, visited=visited):
                attrs, fields = self._attrs(node), self._fields(node)
                symbol = str(attrs.get("symbol_id") or "")
                if symbol.startswith(("pine:variable:strategy.", "pine:variable:barstate.")):
                    self._request_error(
                        node,
                        "broker/barstate dependencies in request expressions are not supported",
                    )
                if attrs.get("ast_kind") == "CallExpr":
                    info = attrs.get("call", {})
                    sid = str(info.get("symbol_id", ""))
                    if sid.startswith("user:function:"):
                        self._request_error(
                            node, "request UDF dependency slicing is not yet supported"
                        )
                    target = self.target.call_bindings.get(
                        (sid, str(info.get("overload_id")), str(info.get("call_form")))
                    )
                    if (
                        target is None
                        or target.disposition != "TARGET_DIRECT"
                        or target.state_model == "COMPILED_REQUEST_EXPRESSION"
                    ):
                        self._request_error(
                            node, "nested or delegated request expression is not supported"
                        )
                if attrs.get("ast_kind") == "Identifier":
                    name = fields.get("name")
                    local = self._lookup_local(
                        str(attrs.get("scope_id") or "scope:global"), str(name)
                    )
                    if local is not None:
                        declaration = declarations.get(name)
                        if (
                            declaration is None
                            or name in mutated
                            or local != self.local_names.get(("scope:global", name))
                        ):
                            self._request_error(
                                node, "request expression needs an immutable global dependency"
                            )
                        if declaration in visiting:
                            self._request_error(node, "cyclic request expression dependency")
                        if declaration not in visited:
                            visiting.add(declaration)
                            for initializer in self._role(declaration, "initializer"):
                                visit(initializer)
                            visiting.remove(declaration)
                            visited.add(declaration)
                            dependencies.append(declaration)
                children = (
                    self._role(node, "arguments")
                    if attrs.get("ast_kind") == "CallExpr"
                    else self._node(node).child_ir_ids
                )
                for child in children:
                    visit(child)

            visit(expression)
            shape = self._request_shape(expression)
            dynamic = any(
                self._node(args[name]).result_type is not None
                and self._node(args[name]).result_type.qualifier == "series"
                for name in ("symbol", "timeframe", "resolution")
                if name in args
            )
            enabled = self.metadata.declaration.get("arguments", {}).get(
                "dynamic_requests", self.plan.pine_version >= 6
            )
            if type(enabled) is not bool:
                self._request_error(key, "dynamic_requests must be a compile-time bool")
            if not enabled and (dynamic or self._attrs(key).get("scope_id") != "scope:global"):
                self._request_error(
                    key,
                    "dynamic requests are disabled; local/context-varying calls are not admitted",
                )
            identity = (
                "sha256:"
                + hashlib.sha256(
                    (self.plan.source_hash + key + self.target.content_hash).encode()
                ).hexdigest()
            )
            self.request_methods[key] = (
                self._safe("expression", "request", key),
                expression,
                dependencies,
                shape,
                dynamic,
                identity,
            )

    def _request_error(self, key, message):
        raise BundleInvariantError(
            "A2P_REQUEST_EXPRESSION",
            message,
            details={"ir_id": key, "source_node_id": self._node(key).source.node_id},
        )

    def _request_shape(self, key):
        if self._attrs(key).get("ast_kind") == "TupleExpr":
            parts = [self._request_shape(child) for child in self._role(key, "elements")]
            if any("tuple_of" in item for item in parts):
                self._request_error(key, "nested tuple request results are unsupported")
            return "_PineLibResultShape.tuple_of(" + ", ".join(parts) + ")"
        typ = self._node(key).result_type
        if typ is None or typ.base not in {"float", "int", "bool", "string"}:
            self._request_error(key, "request result needs an exact scalar or scalar-tuple type")
        return f"_PineLibResultShape.scalar({typ.base!r})"

    def _request_expression_argument(self, key):
        method, _, _, shape, dynamic, identity = self.request_methods[key]
        return f"_PineLibRequestExpression(self.runtime, type(self), {method!r}, {identity!r}, {shape}, {dynamic!r})"

    def _emit_request_methods(self):
        for method, expression, dependencies, _, _, _ in self.request_methods.values():
            self.writer.line(f"def {method}(self):")
            self.writer.indent()
            for declaration in dependencies:
                self._emit_statement(declaration)
            self.writer.line(
                f"return {self._expr(expression)}", ir_ids=self._subtree(expression), origin="PINE"
            )
            self.writer.dedent()
            self.writer.line()
