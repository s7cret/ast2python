"""Lower checked nominal types through the single PineLib heap/state owner."""

from ast2python.errors import BundleInvariantError


class NominalEmissionMixin:
    def _prepare_nominal_types(self):
        self.nominal_types = {}
        self.nominal_declarations = {}
        self.callable_declarations = {}
        self.callable_names = {}
        self.method_receivers = {}
        self.assignment_results = {}
        if not self.exact_pinelib:
            return
        for key in self.plan.ordered_ir_ids:
            attrs, fields = self._attrs(key), self._fields(key)
            kind = attrs.get("ast_kind")
            if kind not in {"TypeDeclaration", "EnumDeclaration"}:
                continue
            self._require_language_contract("compiler.nominal_types.v1")
            if self.plan.pine_version < 5:
                raise BundleInvariantError("A2P_NOMINAL_VERSION", "nominal types require Pine v5+")
            name = fields["name"]
            prefix = "udt" if kind == "TypeDeclaration" else "enum"
            identity = f"{prefix}:{self.plan.source_hash}:{name}:{self._node(key).source.node_id}"
            self.nominal_types[name] = identity
            self.nominal_declarations[name] = key

    def _runtime_type(self, dtype):
        if dtype in self.nominal_types:
            return self.nominal_types[dtype]
        if "<" not in dtype or not dtype.endswith(">"):
            return dtype
        base, inner = dtype.split("<", 1)
        inner = inner[:-1]
        depth, begin, parts = 0, 0, []
        for index, character in enumerate(inner):
            depth += (character == "<") - (character == ">")
            if character == "," and depth == 0:
                parts.append(self._runtime_type(inner[begin:index].strip()))
                begin = index + 1
        parts.append(self._runtime_type(inner[begin:].strip()))
        return base + "<" + ",".join(parts) + ">"

    def _nominal_member(self, key):
        owner = self._role(key, "object")
        if len(owner) != 1:
            return None
        member = self._fields(key).get("member")
        owner_name = self._fields(owner[0]).get("name")
        declaration = self.nominal_declarations.get(owner_name)
        if declaration and self._attrs(declaration)["ast_kind"] == "EnumDeclaration":
            members = self._role(declaration, "members")
            names = [self._fields(item)["name"] for item in members]
            if member not in names:
                raise BundleInvariantError("A2P_ENUM_MEMBER", "unknown nominal enum member")
            dtype = self.nominal_types[owner_name]
            return f"self.runtime.enum_value_v1({dtype!r}, {member!r}, {names.index(member)})"
        typ = self._node(owner[0]).result_type
        if typ and self._runtime_type(typ.base).startswith("udt:"):
            return f"self.runtime.get_udt_field_v1({self._expr(owner[0])}, {member!r})"
        return None

    def _nominal_call(self, key, call, rendered):
        symbol = str(call["symbol_id"])
        declarations = [
            declaration
            for declaration in self.nominal_declarations.values()
            if self._attrs(declaration).get("symbol_id") == symbol
        ]
        if len(declarations) != 1:
            raise BundleInvariantError("A2P_UDT_DECLARATION", "constructor lacks exact declaration")
        declaration = declarations[0]
        if self._attrs(declaration).get("ast_kind") != "TypeDeclaration" or call.get(
            "call_form"
        ) not in {"UDT_CONSTRUCTOR", "UDT_COPY"}:
            raise BundleInvariantError("A2P_UDT_DECLARATION", "call lacks a checked UDT operation")
        dtype = self.nominal_types[self._fields(declaration)["name"]]
        identity = f"self.runtime.reference_id_v1({self._node(key).source.node_id!r})"
        if call.get("call_form") == "UDT_COPY":
            values = list(rendered.values())
            if not values:
                callee = self._role(key, "callee")[0]
                values = [self._expr(self._role(callee, "object")[0])]
            if len(values) != 1:
                raise BundleInvariantError("A2P_UDT_COPY", "copy requires one checked receiver")
            return f"self.runtime.copy_udt_v1({values[0]}, {identity})"
        fields, field_types, varip_fields = [], {}, []
        for field in self._role(declaration, "fields"):
            attributes = self._fields(field)
            name = attributes["name"]
            field_type = self._runtime_type(self._type_ref_text(self._role(field, "type_ref")[0]))
            field_types[name] = field_type
            value = rendered.get(name)
            if value is None:
                defaults = self._role(field, "default_value")
                value = (
                    self._expr(defaults[0])
                    if defaults
                    else (
                        "False"
                        if field_type == "bool" and self.plan.pine_version >= 6
                        else "_PineLibNA"
                    )
                )
            fields.append(f"{name!r}: {value}")
            if attributes.get("mode") == "varip":
                varip_fields.append(name)
        if set(rendered) - set(field_types):
            raise BundleInvariantError("A2P_UDT_ARGUMENT", "constructor has unknown fields")
        return (
            f"self.runtime.new_udt_v1({identity}, {dtype!r}, "
            "{" + ", ".join(fields) + "}, "
            f"field_types={field_types!r}, varip_fields={tuple(varip_fields)!r})"
        )

    def _nominal_assignment(self, key, target, value):
        if self._attrs(target).get("ast_kind") != "MemberAccessExpr":
            return False
        owner = self._role(target, "object")
        typ = self._node(owner[0]).result_type if owner else None
        if not typ or not self._runtime_type(typ.base).startswith("udt:"):
            raise BundleInvariantError(
                "A2P_UDT_ASSIGNMENT", "field assignment lacks typed UDT owner"
            )
        # Evaluate the receiver once even for compound assignment: it may be a
        # stateful function call or return an independently allocated object.
        receiver = self._safe("receiver", "field", key)
        self.writer.line(
            f"{receiver} = {self._expr(owner[0])}", ir_ids=self._subtree(target), origin="PINE"
        )
        field = self._fields(target)["member"]
        expression = self._expr(value)
        operator = self._fields(key)["op"]
        if operator not in {":=", "="}:
            expression = (
                f"self.runtime.op_operator_binary({operator[:-1]!r}, "
                f"self.runtime.get_udt_field_v1({receiver}, {field!r}), {expression})"
            )
        self.writer.line(
            f"self.runtime.set_udt_field_v1({receiver}, {field!r}, {expression})",
            ir_ids=self._subtree(key),
            origin="PINE",
        )
        self.assignment_results[key] = f"self.runtime.get_udt_field_v1({receiver}, {field!r})"
        return True

    def _assignment_value(self, key):
        if key in self.assignment_results:
            return self.assignment_results[key]
        return self._expr(self._role(key, "target")[0])
