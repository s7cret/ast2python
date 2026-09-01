from __future__ import annotations

import ast
import hashlib
import keyword
import re
from dataclasses import dataclass
from typing import Any, cast

from ast2python.admission.canonical import thaw_json
from ast2python.emission.source_map import PythonPosition, SourceMapEntry, SourceMapV2
from ast2python.errors import BundleInvariantError
from ast2python.lowering.model import IRNode, LoweringPlan
from ast2python.lowering.target import TargetCallBinding, TargetManifest, TargetValueBinding

_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NON_IDENTIFIER = re.compile(r"[^A-Za-z0-9_]+")
_HISTORY_SERIES_SYMBOLS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "time",
        "time_close",
        "bar_index",
        "last_bar_index",
    }
)


@dataclass(frozen=True, slots=True)
class EmittedPythonModule:
    module_name: str
    entrypoint_class: str
    code: str
    code_hash: str
    source_map: SourceMapV2
    import_manifest: tuple[str, ...]

    def to_summary(self) -> dict[str, Any]:
        return {
            "module_name": self.module_name,
            "entrypoint_class": self.entrypoint_class,
            "code_hash": self.code_hash,
            "source_map_hash": self.source_map.content_hash,
            "import_manifest": list(self.import_manifest),
            "line_count": len(self.code.splitlines()),
        }


class _Writer:
    def __init__(self, plan: LoweringPlan) -> None:
        self.plan = plan
        self.lines: list[str] = []
        self.indent_level = 0
        self.entries: list[SourceMapEntry] = []
        self.mapped_ir_ids: set[str] = set()

    @property
    def line_number(self) -> int:
        return len(self.lines) + 1

    def indent(self) -> None:
        self.indent_level += 1

    def dedent(self) -> None:
        self.indent_level = max(0, self.indent_level - 1)

    def line(
        self,
        text: str = "",
        *,
        ir_ids: tuple[str, ...] = (),
        origin: str = "SCAFFOLD",
    ) -> int:
        rendered = f"{'    ' * self.indent_level}{text}" if text else ""
        line_number = self.line_number
        self.lines.append(rendered)
        for ir_id in ir_ids:
            if ir_id in self.mapped_ir_ids:
                continue
            node = self.plan.nodes[ir_id]
            self.entries.append(
                SourceMapEntry(
                    python_start=PythonPosition(
                        line_number, len(rendered) - len(rendered.lstrip())
                    ),
                    python_end=PythonPosition(line_number, len(rendered)),
                    source_node_id=node.source.node_id,
                    source_span=thaw_json(node.source.span),
                    ir_id=ir_id,
                    origin="PINE" if origin == "PINE" else "LOWERING",
                    semantic_rule_ids=node.semantic_rule_ids,
                )
            )
            self.mapped_ir_ids.add(ir_id)
        if not ir_ids and origin == "SCAFFOLD" and text:
            self.entries.append(
                SourceMapEntry(
                    python_start=PythonPosition(line_number, 0),
                    python_end=PythonPosition(line_number, len(rendered)),
                    source_node_id=None,
                    source_span=None,
                    ir_id=None,
                    origin="SCAFFOLD",
                )
            )
        return line_number

    def render(self) -> str:
        return "\n".join(self.lines) + "\n"


class _DirectEmitter:
    def __init__(self, plan: LoweringPlan, target: TargetManifest) -> None:
        self.plan = plan
        self.target = target
        self.writer = _Writer(plan)
        self.exact_pinelib = target.release_acceptance == "EXACT_PINELIB_TARGET_MANIFEST_V2"
        self.local_names: dict[tuple[str, str], str] = {}
        self.series_ids: dict[tuple[str, str], str] = {}
        self.names_by_source: dict[str, str] = {}
        self.functions_by_name: dict[str, str] = {}
        self.function_ir_ids: set[str] = set()
        self.source_to_ir: dict[str, str] = {}
        for disposition in plan.dispositions:
            if disposition.ir_ids:
                self.source_to_ir[disposition.source_node_id] = disposition.ir_ids[0]
        self._prepare_names()
        self.direct_imports: dict[tuple[str, str], str] = {}
        self.direct_call_aliases: dict[tuple[str, str, str], str] = {}
        self.direct_value_aliases: dict[str, str] = {}
        self.direct_operation_aliases: dict[str, str] = {}
        self._prepare_direct_imports()

    def _node(self, ir_id: str) -> IRNode:
        return self.plan.nodes[ir_id]

    def _attrs(self, ir_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], thaw_json(self._node(ir_id).attributes))

    def _fields(self, ir_id: str) -> dict[str, Any]:
        value = self._attrs(ir_id).get("fields", {})
        return value if isinstance(value, dict) else {}

    def _roles(self, ir_id: str) -> dict[str, tuple[str, ...]]:
        value = self._attrs(ir_id).get("child_roles", {})
        if not isinstance(value, dict):
            return {}
        return {
            str(role): tuple(child for child in children if isinstance(child, str))
            for role, children in value.items()
            if isinstance(children, list)
        }

    def _role(self, ir_id: str, role: str) -> tuple[str, ...]:
        return self._roles(ir_id).get(role, ())

    def _safe(self, value: str, prefix: str, identity: str) -> str:
        slug = _NON_IDENTIFIER.sub("_", value).strip("_") or prefix
        if slug[0].isdigit() or keyword.iskeyword(slug):
            slug = f"{prefix}_{slug}"
        suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
        return f"{prefix}_{slug}_{suffix}"

    def _prepare_names(self) -> None:
        for ir_id in self.plan.ordered_ir_ids:
            attrs = self._attrs(ir_id)
            fields = self._fields(ir_id)
            kind = attrs.get("ast_kind")
            scope = str(attrs.get("scope_id") or "scope:global")
            name = fields.get("name")
            if kind in {"VarDeclaration", "Parameter", "TupleTarget"} and isinstance(name, str):
                existing_names = {
                    py_name
                    for (_candidate_scope, candidate_name), py_name in self.local_names.items()
                    if candidate_name == name
                }
                py_name = (
                    next(iter(existing_names))
                    if len(existing_names) == 1
                    else self._safe(name, "var", self._node(ir_id).source.node_id)
                )
                self.local_names[(scope, name)] = py_name
                self.names_by_source[self._node(ir_id).source.node_id] = py_name
                if kind == "VarDeclaration" and scope == "scope:global":
                    initializer = self._role(ir_id, "initializer")
                    result_type = (
                        self._node(initializer[0]).result_type if len(initializer) == 1 else None
                    )
                    if result_type is not None and result_type.base in {
                        "bool",
                        "color",
                        "float",
                        "int",
                        "string",
                    }:
                        self.series_ids[(scope, name)] = (
                            f"series:{self._node(ir_id).source.node_id}"
                        )
            elif kind == "ForRangeStructure":
                variable = fields.get("variable")
                if isinstance(variable, str):
                    self.local_names[(scope, variable)] = self._safe(variable, "loop", ir_id)
            elif kind in {"FunctionDeclaration", "MethodDeclaration"} and isinstance(name, str):
                py_name = self._safe(name, "udf", self._node(ir_id).source.node_id)
                self.functions_by_name[name] = py_name
                self.function_ir_ids.add(ir_id)

    def _lookup_local(self, scope: str, name: str) -> str | None:
        exact = self.local_names.get((scope, name))
        if exact is not None:
            return exact
        matches = [
            py_name
            for (candidate_scope, candidate), py_name in self.local_names.items()
            if candidate == name
        ]
        return matches[0] if len(set(matches)) == 1 else None

    def _series_identity(self, ir_id: str) -> str | None:
        attrs = self._attrs(ir_id)
        fields = self._fields(ir_id)
        if attrs.get("ast_kind") != "Identifier":
            return None
        name = str(fields.get("name") or "")
        scope = str(attrs.get("scope_id") or "scope:global")
        local = self.series_ids.get((scope, name))
        if local is not None:
            return local
        symbol_id = attrs.get("symbol_id")
        if (
            isinstance(symbol_id, str)
            and symbol_id == f"pine:variable:{name}"
            and name in _HISTORY_SERIES_SYMBOLS
        ):
            return name
        return None

    def _prepare_direct_imports(self) -> None:
        if not self.exact_pinelib:
            return
        for opcode in sorted(self.plan.required_operations):
            operation = self.target.operations[opcode]
            if operation.python_module is None:
                continue
            import_key = (operation.python_module, operation.python_name)
            alias = self.direct_imports.get(import_key)
            if alias is None:
                alias = self._safe(
                    operation.python_name,
                    "pl",
                    f"{operation.python_module}.{operation.python_name}",
                )
                self.direct_imports[import_key] = alias
            self.direct_operation_aliases[opcode] = alias
        for ir_id in self.plan.ordered_ir_ids:
            call = self._attrs(ir_id).get("call")
            if not isinstance(call, dict):
                continue
            key = (
                str(call.get("symbol_id")),
                str(call.get("overload_id")),
                str(call.get("call_form")),
            )
            binding = self.target.call_bindings.get(key)
            if binding is None or binding.python_module is None:
                continue
            import_key = (binding.python_module, binding.python_name)
            alias = self.direct_imports.get(import_key)
            if alias is None:
                alias = self._safe(
                    binding.python_name,
                    "pl",
                    f"{binding.python_module}.{binding.python_name}",
                )
                self.direct_imports[import_key] = alias
            self.direct_call_aliases[key] = alias
        for ir_id in self.plan.ordered_ir_ids:
            symbol_id = self._attrs(ir_id).get("symbol_id")
            if not isinstance(symbol_id, str):
                continue
            value_binding = self.target.value_bindings.get(symbol_id)
            if (
                value_binding is None
                or value_binding.disposition != "TARGET_DIRECT"
                or value_binding.python_module is None
                or value_binding.python_name is None
            ):
                continue
            import_key = (value_binding.python_module, value_binding.python_name)
            alias = self.direct_imports.get(import_key)
            if alias is None:
                alias = self._safe(
                    value_binding.python_name,
                    "pl",
                    f"{value_binding.python_module}.{value_binding.python_name}",
                )
                self.direct_imports[import_key] = alias
            self.direct_value_aliases[symbol_id] = alias

    def _subtree(self, ir_id: str) -> tuple[str, ...]:
        result: list[str] = []
        stack = [ir_id]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen or current not in self.plan.nodes:
                continue
            seen.add(current)
            result.append(current)
            stack.extend(reversed(self._node(current).child_ir_ids))
        return tuple(result)

    def _runtime_operation(self, opcode: str, *arguments: str) -> str:
        operation = self.target.operations[opcode]
        if self.exact_pinelib:
            alias = self.direct_operation_aliases.get(opcode)
            if alias is None or operation.python_module is None:
                raise BundleInvariantError(
                    "A2P_PINELIB_PRIMITIVE_MISSING",
                    "exact PineLib manifest declares no direct primitive ABI for the operation",
                    details={"opcode": opcode},
                )
            rendered: list[str] = []
            for binding in operation.parameter_bindings:
                binding_kind = binding.get("binding")
                if binding_kind == "INJECTED" and binding.get("source") == "RUNTIME_TRANSACTION":
                    rendered.append("self.runtime")
                    continue
                if binding_kind == "OPERATION_ARGUMENT":
                    source_index = binding.get("source_index")
                    if type(source_index) is int and 0 <= source_index < len(arguments):
                        rendered.append(arguments[source_index])
                        continue
                raise BundleInvariantError(
                    "A2P_PINELIB_PRIMITIVE_BINDING",
                    "exact PineLib primitive parameter binding is invalid",
                    details={"opcode": opcode, "binding": dict(binding)},
                )
            return f"{alias}({', '.join(rendered)})"
        return f"self.runtime.{operation.python_name}({', '.join(arguments)})"

    def _value(self, ir_id: str, binding: TargetValueBinding) -> str:
        if self.plan.pine_version not in binding.supported_pine_versions:
            raise BundleInvariantError(
                "A2P_PINELIB_VALUE_VERSION",
                "exact PineLib value is unavailable for the source Pine version",
                details={"ir_id": ir_id, "symbol_id": binding.symbol_id},
            )
        if binding.disposition == "REFERENCE_RUNTIME_ATTRIBUTE":
            if binding.python_name is None:
                raise BundleInvariantError(
                    "A2P_EMIT_VALUE_BINDING", "reference value binding lacks a Python name"
                )
            return f"self.runtime.{binding.python_name}"
        if binding.disposition == "TARGET_DELEGATED":
            if not all(
                isinstance(item, str) and item
                for item in (
                    binding.delegation_owner,
                    binding.delegation_schema_id,
                    binding.delegation_capability_id,
                )
            ):
                raise BundleInvariantError(
                    "A2P_PINELIB_VALUE_DELEGATION",
                    "delegated PineLib value identity is incomplete",
                )
            return (
                "self.runtime.resolve_delegated_value("
                f"owner={binding.delegation_owner!r}, "
                f"schema_id={binding.delegation_schema_id!r}, "
                f"capability_id={binding.delegation_capability_id!r})"
            )
        if binding.disposition != "TARGET_DIRECT":
            raise BundleInvariantError(
                "A2P_PINELIB_VALUE_UNSUPPORTED",
                binding.diagnostic or "exact PineLib target does not provide this runtime value",
                details={
                    "ir_id": ir_id,
                    "symbol_id": binding.symbol_id,
                    "disposition": binding.disposition,
                },
            )
        alias = self.direct_value_aliases.get(binding.symbol_id)
        if alias is None or binding.python_module is None or binding.python_name is None:
            raise BundleInvariantError(
                "A2P_PINELIB_VALUE_CALLABLE", "exact PineLib value callable import is missing"
            )
        keyword_arguments: list[str] = []
        for parameter_binding in binding.parameter_bindings:
            abi_parameter = str(parameter_binding["abi_parameter"])
            binding_kind = str(parameter_binding["binding"])
            source = parameter_binding.get("source")
            if binding_kind == "ABI_DEFAULT":
                continue
            if binding_kind == "UNBOUND_FAIL_CLOSED":
                raise BundleInvariantError(
                    "A2P_PINELIB_UNBOUND_VALUE_PARAMETER",
                    "PineLib runtime value ABI parameter is explicitly unbound",
                    details={
                        "abi_parameter": abi_parameter,
                        "symbol_id": binding.symbol_id,
                    },
                )
            if binding_kind == "INJECTED" and source == "RUNTIME_TRANSACTION":
                keyword_arguments.append(f"{abi_parameter}=self.runtime")
                continue
            raise BundleInvariantError(
                "A2P_PINELIB_VALUE_PARAMETER_BINDING",
                "unsupported PineLib runtime value parameter binding",
                details={
                    "abi_parameter": abi_parameter,
                    "binding": binding_kind,
                    "source": source,
                },
            )
        return f"{alias}({', '.join(keyword_arguments)})"

    def _identifier(self, ir_id: str) -> str:
        attrs = self._attrs(ir_id)
        fields = self._fields(ir_id)
        name = str(fields.get("name") or "")
        scope = str(attrs.get("scope_id") or "scope:global")
        local = self._lookup_local(scope, name)
        if local is not None:
            return local
        if name in self.functions_by_name:
            return f"self.{self.functions_by_name[name]}"
        symbol_id = attrs.get("symbol_id")
        if isinstance(symbol_id, str):
            binding = self.target.value_bindings.get(symbol_id)
            if binding is not None:
                return self._value(ir_id, binding)
        if name == "na" or symbol_id == "pine:variable:na":
            raise BundleInvariantError(
                "A2P_NA_UNSUPPORTED_FAIL_CLOSED",
                "pine:variable:na is unsupported fail-closed for exact-target lowering",
                details={"ir_id": ir_id, "symbol_id": symbol_id},
            )
        raise BundleInvariantError(
            "A2P_EMIT_VALUE_BINDING",
            f"no exact target value binding for identifier {name!r}",
            details={"ir_id": ir_id, "symbol_id": symbol_id},
        )

    def _call(self, ir_id: str) -> str:
        attrs = self._attrs(ir_id)
        call = attrs.get("call")
        if not isinstance(call, dict):
            raise BundleInvariantError("A2P_EMIT_CALL", "IR call lacks producer call facts")
        arguments_by_source = {
            self._node(argument_ir).source.node_id: argument_ir
            for argument_ir in self._role(ir_id, "arguments")
        }
        ordered = sorted(call.get("arguments", []), key=lambda row: row["parameter_index"])
        rendered: list[str] = []
        rendered_by_parameter: dict[str, str] = {}
        delegated_positional: list[str] = []
        delegated_named: list[tuple[str, str]] = []
        for argument in ordered:
            argument_ir = arguments_by_source.get(argument["argument_node_id"])
            if argument_ir is None:
                raise BundleInvariantError(
                    "A2P_EMIT_CALL_ARGUMENT", "call argument is absent from IR roles"
                )
            value_ir = self._role(argument_ir, "value")
            if len(value_ir) != 1:
                raise BundleInvariantError(
                    "A2P_EMIT_CALL_ARGUMENT", "Argument must contain one value"
                )
            value = self._expr(value_ir[0])
            rendered_by_parameter[str(argument["parameter_name"])] = value
            if argument["binding"] == "named":
                rendered.append(f"{argument['parameter_name']}={value}")
                delegated_named.append((str(argument["parameter_name"]), value))
            else:
                rendered.append(value)
                delegated_positional.append(value)
        symbol_id = str(call["symbol_id"])
        if symbol_id.startswith("user:function:"):
            callee = str(call["callee"])
            function_name = self.functions_by_name.get(callee)
            if function_name is None:
                raise BundleInvariantError(
                    "A2P_EMIT_UDF_BINDING", "user function declaration is missing"
                )
            return f"self.{function_name}({', '.join(rendered)})"
        key = (symbol_id, str(call["overload_id"]), str(call["call_form"]))
        binding: TargetCallBinding | None = self.target.call_bindings.get(key)
        if binding is None or self.plan.pine_version not in binding.supported_pine_versions:
            raise BundleInvariantError(
                "A2P_TARGET_CALL_BINDING", "exact target call binding is missing"
            )
        if binding.disposition == "TARGET_DELEGATED":
            if not all(
                isinstance(item, str) and item
                for item in (
                    binding.delegation_owner,
                    binding.delegation_schema_id,
                    binding.delegation_capability_id,
                )
            ):
                raise BundleInvariantError(
                    "A2P_PINELIB_CALL_DELEGATION",
                    "delegated PineLib call identity is incomplete",
                )
            span = thaw_json(self._node(ir_id).source.span)
            positional = "[" + ", ".join(delegated_positional) + "]"
            named = "{" + ", ".join(
                f"{name!r}: {value}" for name, value in delegated_named
            ) + "}"
            source_span = (
                "_PineLibSourceSpan("
                f"source_hash={self.plan.source_hash!r}, "
                "file_id='generated.pine', "
                f"start_line={int(span['start_line'])}, "
                f"start_column={int(span['start_col'])}, "
                f"end_line={int(span['end_line'])}, "
                f"end_column={int(span['end_col'])})"
            )
            result_type = self._node(ir_id).result_type
            if result_type is not None and result_type.base not in {"void", "na"}:
                raise BundleInvariantError(
                    "A2P_DELEGATED_RESULT_REQUIRES_COMMIT",
                    "value-producing delegated calls cannot use a dispatch receipt as a Pine value",
                    details={
                        "symbol_id": binding.symbol_id,
                        "result_type": result_type.base,
                    },
                )
            receiver = self._role(ir_id, "receiver")
            if receiver:
                delegated_positional.insert(0, self._expr(receiver[0]))
            return (
                "self.runtime.dispatch_delegated("
                f"owner={binding.delegation_owner!r}, "
                f"schema_id={binding.delegation_schema_id!r}, "
                f"capability_id={binding.delegation_capability_id!r}, "
                f"symbol_id={binding.symbol_id!r}, "
                f"overload_id={binding.overload_id!r}, "
                f"arguments={{'positional': {positional}, 'named': {named}}}, "
                f"call_site_id={self._node(ir_id).source.node_id!r}, "
                f"source_span={source_span})"
            )
        if self.exact_pinelib:
            alias = self.direct_call_aliases.get(key)
            if alias is None or binding.python_module is None:
                raise BundleInvariantError(
                    "A2P_PINELIB_CALLABLE",
                    "exact PineLib callable import is missing",
                )
            keyword_arguments: list[str] = []
            consumed: set[str] = set()
            for parameter_binding in binding.parameter_bindings:
                abi_parameter = str(parameter_binding["abi_parameter"])
                binding_kind = str(parameter_binding["binding"])
                source = parameter_binding.get("source")
                if binding_kind == "SOURCE_PARAMETER":
                    source_name = str(source)
                    bound_value = rendered_by_parameter.get(source_name)
                    if bound_value is not None:
                        keyword_arguments.append(f"{abi_parameter}={bound_value}")
                        consumed.add(source_name)
                    continue
                if binding_kind == "ABI_DEFAULT":
                    continue
                if binding_kind == "UNBOUND_FAIL_CLOSED":
                    raise BundleInvariantError(
                        "A2P_PINELIB_UNBOUND_PARAMETER",
                        "PineLib ABI parameter is explicitly unbound",
                        details={"abi_parameter": abi_parameter, "binding_key": list(key)},
                    )
                if binding_kind == "METHOD_RECEIVER":
                    callee_ir_ids = self._role(ir_id, "callee")
                    receiver_ir_ids = (
                        self._role(callee_ir_ids[0], "object") if len(callee_ir_ids) == 1 else ()
                    )
                    if len(receiver_ir_ids) != 1:
                        raise BundleInvariantError(
                            "A2P_PINELIB_METHOD_RECEIVER",
                            "exact method receiver is absent from the call IR",
                        )
                    keyword_arguments.append(f"{abi_parameter}={self._expr(receiver_ir_ids[0])}")
                    continue
                if binding_kind != "INJECTED":
                    raise BundleInvariantError(
                        "A2P_PINELIB_PARAMETER_BINDING",
                        "unknown PineLib ABI parameter binding",
                    )
                if source == "RUNTIME_TRANSACTION":
                    injected = "self.runtime"
                elif source in {
                    "SOURCE_LOCATION_STATE_ID",
                    "SOURCE_LOCATION_OBJECT_ID",
                }:
                    injected = repr(f"{self._node(ir_id).source.node_id}:{abi_parameter}")
                elif source == "SOURCE_SPAN":
                    span = thaw_json(self._node(ir_id).source.span)
                    injected = (
                        "_PineLibSourceSpan("
                        f"source_hash={self.plan.source_hash!r}, "
                        "file_id='generated.pine', "
                        f"start_line={int(span['start_line'])}, "
                        f"start_column={int(span['start_col'])}, "
                        f"end_line={int(span['end_line'])}, "
                        f"end_column={int(span['end_col'])})"
                    )
                elif source == "SEMANTIC_RETURN_TYPE":
                    injected = repr(binding.return_type)
                elif source == "SEMANTIC_TYPE_DESCRIPTOR":
                    result_type = self._node(ir_id).result_type
                    pine_type = result_type.base if result_type is not None else "unknown"
                    if "<" not in pine_type or not pine_type.endswith(">"):
                        raise BundleInvariantError(
                            "A2P_PINELIB_TYPE_DESCRIPTOR",
                            "generic constructor lacks an exact semantic result type",
                            details={"pine_type": pine_type},
                        )
                    injected = repr(pine_type.split("<", 1)[1][:-1])
                else:
                    raise BundleInvariantError(
                        "A2P_PINELIB_INJECTION",
                        "unsupported PineLib injected parameter source",
                        details={"source": source, "abi_parameter": abi_parameter},
                    )
                keyword_arguments.append(f"{abi_parameter}={injected}")
            unsupported = set(rendered_by_parameter) - consumed
            if unsupported:
                raise BundleInvariantError(
                    "A2P_PINELIB_SOURCE_PARAMETER",
                    "source arguments are not bound to the PineLib ABI",
                    details={"parameters": sorted(unsupported)},
                )
            return f"{alias}({', '.join(keyword_arguments)})"
        return f"self.runtime.{binding.python_name}({', '.join(rendered)})"

    def _switch_expression(self, ir_id: str) -> str:
        selectors = self._role(ir_id, "expression")
        if len(selectors) > 1:
            raise BundleInvariantError(
                "A2P_EMIT_SWITCH", "switch must contain at most one selector expression"
            )
        cases = self._role(ir_id, "cases")
        if not cases:
            raise BundleInvariantError("A2P_EMIT_SWITCH", "switch contains no cases")
        selector_name = self._safe("switch", "switch", ir_id)
        rendered = "None"
        default_seen = False
        for case in reversed(cases):
            conditions = self._role(case, "condition")
            bodies = self._role(case, "body")
            if len(conditions) > 1 or len(bodies) != 1:
                raise BundleInvariantError("A2P_EMIT_SWITCH_CASE", "switch case is incomplete")
            if self._attrs(bodies[0]).get("ast_kind") == "Block":
                raise BundleInvariantError(
                    "A2P_EMIT_SWITCH_CASE",
                    "block-bodied switch cannot be emitted as an expression",
                )
            body = self._expr(bodies[0])
            if not conditions:
                if default_seen:
                    raise BundleInvariantError(
                        "A2P_EMIT_SWITCH_CASE", "switch contains multiple default cases"
                    )
                default_seen = True
                rendered = body
                continue
            condition = self._expr(conditions[0])
            test = f"{selector_name} == {condition}" if selectors else f"bool({condition})"
            rendered = f"({body} if {test} else {rendered})"
        if not selectors:
            return rendered
        return f"(lambda {selector_name}: {rendered})({self._expr(selectors[0])})"

    def _expr(self, ir_id: str) -> str:
        attrs = self._attrs(ir_id)
        fields = self._fields(ir_id)
        kind = attrs.get("ast_kind")
        if kind == "Argument":
            values = self._role(ir_id, "value")
            if len(values) != 1:
                raise BundleInvariantError("A2P_EMIT_ARGUMENT", "Argument must contain one value")
            return self._expr(values[0])
        if kind == "Literal":
            return "None" if fields.get("literal_type") == "na" else repr(fields.get("value"))
        if kind == "Identifier":
            return self._identifier(ir_id)
        if kind == "MemberAccessExpr":
            symbol_id = attrs.get("symbol_id")
            if isinstance(symbol_id, str) and symbol_id in self.target.value_bindings:
                return self._value(ir_id, self.target.value_bindings[symbol_id])
            raise BundleInvariantError(
                "A2P_EMIT_VALUE_BINDING", "member access lacks exact value binding"
            )
        if kind == "BinaryExpr":
            left = self._role(ir_id, "left")
            right = self._role(ir_id, "right")
            if len(left) != 1 or len(right) != 1:
                raise BundleInvariantError(
                    "A2P_EMIT_BINARY", "binary expression operands are incomplete"
                )
            operator = str(fields.get("op"))
            if operator in {"and", "or"}:
                return f"({self._expr(left[0])} {operator} {self._expr(right[0])})"
            return self._runtime_operation(
                self._node(ir_id).opcode,
                repr(operator),
                self._expr(left[0]),
                self._expr(right[0]),
            )
        if kind == "UnaryExpr":
            operands = self._role(ir_id, "operand")
            if len(operands) != 1:
                raise BundleInvariantError(
                    "A2P_EMIT_UNARY", "unary expression operand is incomplete"
                )
            return self._runtime_operation(
                self._node(ir_id).opcode, repr(fields.get("op")), self._expr(operands[0])
            )
        if kind == "ConditionalExpr":
            condition = self._role(ir_id, "condition")
            when_true = self._role(ir_id, "if_true")
            when_false = self._role(ir_id, "if_false")
            if not (len(condition) == len(when_true) == len(when_false) == 1):
                raise BundleInvariantError(
                    "A2P_EMIT_CONDITIONAL", "conditional expression is incomplete"
                )
            return f"({self._expr(when_true[0])} if bool({self._expr(condition[0])}) else {self._expr(when_false[0])})"
        if kind == "HistoryRefExpr":
            base = self._role(ir_id, "base")
            offset = self._role(ir_id, "offset")
            if len(base) != 1 or len(offset) != 1:
                raise BundleInvariantError("A2P_EMIT_HISTORY", "history reference is incomplete")
            series_identity = self._series_identity(base[0])
            base_expression = (
                repr(series_identity) if series_identity is not None else self._expr(base[0])
            )
            return self._runtime_operation(
                self._node(ir_id).opcode,
                base_expression,
                self._expr(offset[0]),
            )
        if kind == "TupleExpr":
            return (
                "(" + ", ".join(self._expr(child) for child in self._role(ir_id, "elements")) + ",)"
            )
        if kind == "CallExpr":
            return self._call(ir_id)
        if kind == "SwitchStructure":
            return self._switch_expression(ir_id)
        raise BundleInvariantError(
            "A2P_EMIT_EXPRESSION",
            f"AST kind {kind!r} cannot be emitted as an expression",
            details={"ir_id": ir_id},
        )

    def _emit_block(self, block_ir: str, *, return_last: bool = False) -> None:
        statements = list(self._role(block_ir, "statements"))
        if not statements:
            self.writer.line("pass", ir_ids=(block_ir,), origin="PINE")
            return
        self.writer.line("# block", ir_ids=(block_ir,), origin="PINE")
        for index, statement in enumerate(statements):
            if return_last and index == len(statements) - 1:
                kind = self._attrs(statement).get("ast_kind")
                if kind == "ExpressionStatement":
                    expression = self._role(statement, "expression")
                    self.writer.line(
                        f"return {self._expr(expression[0])}",
                        ir_ids=self._subtree(statement),
                        origin="PINE",
                    )
                    continue
                if kind == "SwitchStructure":
                    self.writer.line(
                        f"return {self._switch_expression(statement)}",
                        ir_ids=self._subtree(statement),
                        origin="PINE",
                    )
                    continue
            self._emit_statement(statement)

    def _emit_statement(self, ir_id: str) -> None:
        attrs = self._attrs(ir_id)
        fields = self._fields(ir_id)
        kind = attrs.get("ast_kind")
        scope = str(attrs.get("scope_id") or "scope:global")
        if kind == "DeclarationStatement":
            self.writer.line(
                "# Pine declaration (compile time only)",
                ir_ids=self._subtree(ir_id),
                origin="PINE",
            )
            return
        if kind == "ExpressionStatement":
            expression = self._role(ir_id, "expression")
            self.writer.line(self._expr(expression[0]), ir_ids=self._subtree(ir_id), origin="PINE")
            return
        if kind == "VarDeclaration":
            initializer = self._role(ir_id, "initializer")
            name = str(fields.get("name"))
            py_name = self._lookup_local(scope, name)
            if py_name is None or len(initializer) != 1:
                raise BundleInvariantError("A2P_EMIT_VAR", "variable declaration is incomplete")
            initializer_expression = self._expr(initializer[0])
            result_type = self._node(initializer[0]).result_type
            dtype = result_type.base if result_type is not None else "object"
            series_id = (
                self.series_ids.get((scope, name))
                if self.exact_pinelib and dtype in {"bool", "color", "float", "int", "string"}
                else None
            )
            if series_id is not None:
                self.writer.line(
                    f"self.runtime.set_series({series_id!r}, {initializer_expression}, {dtype!r})",
                    ir_ids=self._subtree(ir_id),
                    origin="PINE",
                )
                self.writer.line(f"{py_name} = self.runtime.read_series({series_id!r})")
            else:
                self.writer.line(
                    f"{py_name} = {initializer_expression}",
                    ir_ids=self._subtree(ir_id),
                    origin="PINE",
                )
            return
        if kind == "Reassignment":
            target = self._role(ir_id, "target")
            value = self._role(ir_id, "value")
            if len(target) != 1 or len(value) != 1:
                raise BundleInvariantError("A2P_EMIT_ASSIGNMENT", "reassignment is incomplete")
            target_name = self._identifier(target[0])
            operator = str(fields.get("op"))
            if operator in {":=", "="}:
                text = f"{target_name} = {self._expr(value[0])}"
            else:
                text = f"{target_name} {operator} {self._expr(value[0])}"
            self.writer.line(text, ir_ids=self._subtree(ir_id), origin="PINE")
            return
        if kind == "TupleDeclaration":
            targets = self._role(ir_id, "targets")
            initializer = self._role(ir_id, "initializer")
            names = [self.names_by_source[self._node(target).source.node_id] for target in targets]
            self.writer.line(
                f"{', '.join(names)} = {self._expr(initializer[0])}",
                ir_ids=self._subtree(ir_id),
                origin="PINE",
            )
            return
        if kind == "IfStructure":
            condition = self._role(ir_id, "condition")
            then_block = self._role(ir_id, "then_block")
            self.writer.line(
                f"if bool({self._expr(condition[0])}):",
                ir_ids=(ir_id, *self._subtree(condition[0])),
                origin="PINE",
            )
            self.writer.indent()
            self._emit_block(then_block[0])
            self.writer.dedent()
            for branch in self._role(ir_id, "else_if_branches"):
                branch_condition = self._role(branch, "condition")
                branch_block = self._role(branch, "block")
                self.writer.line(
                    f"elif bool({self._expr(branch_condition[0])}):",
                    ir_ids=(branch, *self._subtree(branch_condition[0])),
                    origin="PINE",
                )
                self.writer.indent()
                self._emit_block(branch_block[0])
                self.writer.dedent()
            else_block = self._role(ir_id, "else_block")
            if else_block:
                self.writer.line("else:")
                self.writer.indent()
                self._emit_block(else_block[0])
                self.writer.dedent()
            return
        if kind == "ForRangeStructure":
            start = self._role(ir_id, "start")
            end = self._role(ir_id, "end")
            step = self._role(ir_id, "step")
            body = self._role(ir_id, "body")
            variable = str(fields.get("variable"))
            py_name = self._lookup_local(scope, variable) or self._safe(variable, "loop", ir_id)
            step_expr = self._expr(step[0]) if step else "1"
            self.writer.line(
                f"for {py_name} in range(int({self._expr(start[0])}), int({self._expr(end[0])}) + 1, int({step_expr})):",
                ir_ids=(
                    ir_id,
                    *self._subtree(start[0]),
                    *self._subtree(end[0]),
                    *(self._subtree(step[0]) if step else ()),
                ),
                origin="PINE",
            )
            self.writer.indent()
            self._emit_block(body[0])
            self.writer.dedent()
            return
        if kind == "ForInStructure":
            iterable = self._role(ir_id, "iterable")
            target = self._role(ir_id, "target")
            body = self._role(ir_id, "body")
            target_fields = self._fields(target[0])
            names = target_fields.get("names", [])
            py_names = [self._safe(str(name), "loop", f"{ir_id}:{name}") for name in names]
            self.writer.line(
                f"for {', '.join(py_names)} in {self._expr(iterable[0])}:",
                ir_ids=(ir_id, target[0], *self._subtree(iterable[0])),
                origin="PINE",
            )
            self.writer.indent()
            self._emit_block(body[0])
            self.writer.dedent()
            return
        if kind == "WhileStructure":
            condition = self._role(ir_id, "condition")
            body = self._role(ir_id, "body")
            self.writer.line(
                f"while bool({self._expr(condition[0])}):",
                ir_ids=(ir_id, *self._subtree(condition[0])),
                origin="PINE",
            )
            self.writer.indent()
            self._emit_block(body[0])
            self.writer.dedent()
            return
        if kind == "BreakStatement":
            self.writer.line("break", ir_ids=(ir_id,), origin="PINE")
            return
        if kind == "ContinueStatement":
            self.writer.line("continue", ir_ids=(ir_id,), origin="PINE")
            return
        if kind == "Block":
            self._emit_block(ir_id)
            return
        if kind in {
            "FunctionDeclaration",
            "MethodDeclaration",
            "TypeDeclaration",
            "EnumDeclaration",
            "ImportDeclaration",
        }:
            return
        raise BundleInvariantError("A2P_EMIT_STATEMENT", f"unsupported statement kind {kind!r}")

    def _emit_function(self, ir_id: str) -> None:
        fields = self._fields(ir_id)
        name = str(fields.get("name"))
        py_name = self.functions_by_name[name]
        parameters = self._role(ir_id, "parameters")
        py_parameters: list[str] = []
        for parameter in parameters:
            parameter_fields = self._fields(parameter)
            parameter_name = str(parameter_fields.get("name"))
            scope = str(self._attrs(parameter).get("scope_id") or "")
            py_parameters.append(
                self._lookup_local(scope, parameter_name)
                or self._safe(parameter_name, "arg", parameter)
            )
        self.writer.line(
            f"def {py_name}(self{', ' if py_parameters else ''}{', '.join(py_parameters)}):",
            ir_ids=(ir_id, *parameters),
            origin="PINE",
        )
        self.writer.indent()
        body = self._role(ir_id, "body")
        if not body:
            self.writer.line("return None")
        elif self._attrs(body[0]).get("ast_kind") == "Block":
            self._emit_block(body[0], return_last=True)
        else:
            self.writer.line(
                f"return {self._expr(body[0])}", ir_ids=self._subtree(body[0]), origin="PINE"
            )
        self.writer.dedent()
        self.writer.line()

    def emit(self) -> str:
        writer = self.writer
        writer.line("from __future__ import annotations")
        writer.line("from typing import Any")
        if self.exact_pinelib:
            writer.line(
                "from pinelib.abi import load_target_manifest as _load_pinelib_target_manifest"
            )
            writer.line("from pinelib.events.common import SourceSpan as _PineLibSourceSpan")
            for (module, python_name), alias in sorted(self.direct_imports.items()):
                writer.line(f"from {module} import {python_name} as {alias}")
        writer.line()
        writer.line(f"PINE_VERSION = {self.plan.pine_version}")
        writer.line(f"TARGET_MANIFEST_HASH = {self.target.content_hash!r}")
        if self.exact_pinelib:
            writer.line(f"PINELIB_TARGET_MANIFEST_HASH = {self.target.target_version!r}")
        writer.line(f"REQUIRED_OPERATIONS = {tuple(sorted(self.plan.required_operations))!r}")
        writer.line(f"REQUIRED_CAPABILITIES = {tuple(sorted(self.plan.required_capabilities))!r}")
        writer.line()
        writer.line("class GeneratedScript:")
        writer.indent()
        writer.line("def __init__(self, runtime: Any) -> None:")
        writer.indent()
        writer.line("self.runtime = runtime")
        if self.exact_pinelib:
            writer.line("actual_hash = _load_pinelib_target_manifest()['content_hash']")
            writer.line("if actual_hash != PINELIB_TARGET_MANIFEST_HASH:")
            writer.indent()
            writer.line("raise RuntimeError(f'PineLib target manifest mismatch: {actual_hash!r}')")
            writer.dedent()
        else:
            writer.line("actual_hash = getattr(runtime, 'target_manifest_hash', None)")
            writer.line("if actual_hash != TARGET_MANIFEST_HASH:")
            writer.indent()
            writer.line("raise RuntimeError(f'target manifest mismatch: {actual_hash!r}')")
            writer.dedent()
            writer.line("supported = frozenset(getattr(runtime, 'supported_operations', ()))")
            writer.line("missing = frozenset(REQUIRED_OPERATIONS) - supported")
            writer.line("if missing:")
            writer.indent()
            writer.line(
                "raise RuntimeError(f'runtime lacks required operations: {sorted(missing)!r}')"
            )
            writer.dedent()
            writer.line("capabilities = frozenset(getattr(runtime, 'capabilities', ()))")
            writer.line("missing_capabilities = frozenset(REQUIRED_CAPABILITIES) - capabilities")
            writer.line("if missing_capabilities:")
            writer.indent()
            writer.line(
                "raise RuntimeError(f'runtime lacks required capabilities: {sorted(missing_capabilities)!r}')"
            )
            writer.dedent()
        writer.dedent()
        writer.line()

        for ir_id in self.plan.ordered_ir_ids:
            if ir_id in self.function_ir_ids:
                self._emit_function(ir_id)

        root = self.plan.root_ir_id
        writer.line("def run(self) -> Any:", ir_ids=(root,), origin="PINE")
        writer.indent()
        root_roles = self._roles(root)
        declaration = root_roles.get("declaration", ())
        for ir_id in declaration:
            self._emit_statement(ir_id)
        for ir_id in root_roles.get("items", ()):
            if ir_id not in self.function_ir_ids:
                self._emit_statement(ir_id)
        writer.line("return None")
        writer.dedent()
        writer.dedent()

        if writer.mapped_ir_ids != set(self.plan.nodes):
            missing = tuple(
                ir_id for ir_id in self.plan.ordered_ir_ids if ir_id not in writer.mapped_ir_ids
            )
            line = writer.line("# compile-time-only source mappings")
            for ir_id in missing:
                node = self._node(ir_id)
                writer.entries.append(
                    SourceMapEntry(
                        python_start=PythonPosition(line, 0),
                        python_end=PythonPosition(line, len(writer.lines[line - 1])),
                        source_node_id=node.source.node_id,
                        source_span=thaw_json(node.source.span),
                        ir_id=ir_id,
                        origin="LOWERING",
                        semantic_rule_ids=node.semantic_rule_ids,
                    )
                )
                writer.mapped_ir_ids.add(ir_id)
        return writer.render()


def _imports_from_code(code: str) -> tuple[str, ...]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return tuple(sorted(modules))


def emit_python_module(
    plan: LoweringPlan,
    target: TargetManifest,
    *,
    module_name: str = "generated_pine_script",
) -> EmittedPythonModule:
    if not _MODULE_RE.fullmatch(module_name) or keyword.iskeyword(module_name):
        raise BundleInvariantError(
            "A2P_EMIT_MODULE_NAME", "module_name must be a safe Python identifier"
        )
    emitter = _DirectEmitter(plan, target)
    code = emitter.emit()
    ast.parse(code)
    imports = _imports_from_code(code)
    forbidden = {name for name in imports if name.split(".", 1)[0] in {"ast2python", "pine2ast"}}
    if forbidden:
        raise BundleInvariantError(
            "A2P_EMIT_FORBIDDEN_IMPORT",
            "generated module imports compiler packages",
            details={"imports": sorted(forbidden)},
        )
    unknown_imports = set(imports) - target.allowed_imports
    if unknown_imports:
        raise BundleInvariantError(
            "A2P_EMIT_IMPORT",
            "generated module uses imports outside target allowlist",
            details={"imports": sorted(unknown_imports)},
        )
    source_map = SourceMapV2.create(tuple(emitter.writer.entries))
    code_hash = "sha256:" + hashlib.sha256(code.encode("utf-8")).hexdigest()
    return EmittedPythonModule(
        module_name=module_name,
        entrypoint_class="GeneratedScript",
        code=code,
        code_hash=code_hash,
        source_map=source_map,
        import_manifest=imports,
    )
