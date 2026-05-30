"""Translator metadata helpers — extracted from translator.py."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ast2python.diagnostics import (
    UNSUPPORTED_DECLARATION_ARG,
    WARNING_NESTED_SECURITY,
    Severity,
)
from ast2python.errors import ScopeResolutionError, UnsupportedBuiltinError
from ast2python.types import TypeInfo, join_qualifiers, make_type_info

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTNode, ASTProgram
    from ast2python.context import VariableInfo


BUILTIN_SERIES = {
    "open", "high", "low", "close", "volume",
    "hl2", "hlc3", "ohlc4",
    "time", "time_close", "bar_index",
    "timenow", "syminfo",
}

FUNCTION_DECLARATIONS = {
    "FunctionDeclaration", "FunctionDecl", "FunctionDefinition",
}

METHOD_DECLARATIONS = {
    "MethodDeclaration", "MethodDecl",
}

UDT_DECLARATIONS = {
    "TypeDeclaration", "UserTypeDeclaration", "UDTDeclaration",
}

ENUM_DECLARATIONS = {
    "EnumDeclaration", "EnumDecl",
}


def member_chain(node: ASTNode) -> str | None:
    if node.kind == "Identifier":
        name = node.field("name")
        return name if isinstance(name, str) else None
    if node.kind == "GenericInstantiationExpr":
        base = node.child("base")
        return None if base is None else member_chain(base)
    if node.kind != "MemberAccessExpr":
        return None
    base = node.child("object")
    member = node.field("member")
    if base is None or not isinstance(member, str):
        return None
    prefix = member_chain(base)
    if prefix is None:
        return None
    return f"{prefix}.{member}"


def literal_value(node: ASTNode) -> Any:
    return node.field("value")


def _call_arguments(node: ASTNode) -> list[tuple[str | None, ASTNode]]:
    """Extract argument name/value pairs from a CallExpr node."""
    if node.kind != "CallExpr":
        return []
    args: list[tuple[str | None, ASTNode]] = []
    for child in node.children():
        if child.kind == "Argument":
            name = child.field("name")
            value = child.child("value")
            if value is not None:
                args.append((str(name) if isinstance(name, str) else None, value))
        elif hasattr(child, "kind") and child.kind == "Identifier":
            args.append((None, child))
    return args


def collect_globals(
    translator: Any, program: ASTProgram
) -> None:
    """Collect global variables, inputs, and series declarations."""
    for item in program.items:
        if item.kind == "ImportDeclaration":
            translator._record_import_alias(item)
            continue
        if item.kind in FUNCTION_DECLARATIONS:
            name = item.field("name")
            if name is not None:
                translator.functions.add(str(name))
            continue
        if item.kind in METHOD_DECLARATIONS:
            name = item.field("name")
            if name is not None:
                translator.methods.add(str(name))
            continue
        if item.kind in UDT_DECLARATIONS | ENUM_DECLARATIONS:
            continue
        if item.kind in {"AlertCondition"}:
            continue
        if item.kind == "TupleDeclaration":
            initializer = item.child("initializer") or item.child("value")
            for name in translator._tuple_targets(item):
                if name == "_":
                    continue
                info = translator.ctx.declare_var(
                    name,
                    type_ref=None,
                    qualifier=item.field("explicit_qualifier"),
                    declaration_kind=str(item.field("mode") or "normal"),
                    is_series=True,
                    is_mutable=True,
                    loc=item.loc,
                )
                if initializer is not None:
                    info.type_info = translator._infer_type_info(initializer)
                    translator.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = (
                        info.type_info.to_dict()
                    )
                elif info.type_ref in {"line", "label", "box", "table", "PineObjectId"}:
                    info.type_info = make_type_info(
                        "PineObjectId", info.qualifier, is_series=info.is_series
                    )
                    translator.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = (
                        info.type_info.to_dict()
                    )
                translator.global_series.append((info, translator._infer_dtype(initializer)))
            continue
        if item.kind == "VarDeclaration":
            initializer = item.child("initializer")
            if initializer is not None and translator._is_input_call(initializer):
                info = translator.ctx.declare_var(
                    item.field("name"),
                    type_ref=translator._type_ref_name(item),
                    qualifier="input",
                    declaration_kind="input",
                    is_series=True,
                    is_mutable=False,
                    loc=item.loc,
                )
                meta = translator._build_input_metadata(item, initializer, info.py_name)
                info.type_info = make_type_info(
                    meta["type"],
                    "input",
                    is_series=True,
                    can_be_na=meta["type"] != "bool",
                )
                translator.ctx.type_metadata[f"global:{info.pine_name}"] = info.type_info.to_dict()
                translator.input_series.append((info, meta["type"], meta))
                translator.ctx.input_metadata.append(meta["public"])
                callee = initializer.child("callee")
                chain = None if callee is None else member_chain(callee)
                if chain is not None:
                    translator.ctx.coverage.builtin(chain)
            else:
                info = translator.ctx.declare_var(
                    item.field("name"),
                    type_ref=translator._type_ref_name(item),
                    qualifier=item.field("explicit_qualifier"),
                    declaration_kind=str(item.field("mode") or "normal"),
                    is_series=True,
                    is_mutable=True,
                    loc=item.loc,
                )
                if initializer is not None:
                    info.type_info = translator._infer_type_info(initializer)
                    translator.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = (
                        info.type_info.to_dict()
                    )
                elif info.type_ref in {"line", "label", "box", "table", "PineObjectId"}:
                    info.type_info = make_type_info(
                        "PineObjectId", info.qualifier, is_series=info.is_series
                    )
                    translator.ctx.type_metadata[f"{info.scope_id}:{info.pine_name}"] = (
                        info.type_info.to_dict()
                    )
                translator.global_series.append((info, translator._infer_dtype(initializer)))
            continue
        if item.kind != "VarDeclaration":
            continue
        for member in item.descendants():
            if member.kind == "CallExpr":
                callee = member.child("callee")
                if callee is not None:
                    chain = member_chain(callee)
                    if chain is not None:
                        translator.ctx.coverage.builtin(chain)


def extract_declaration_title(translator: Any, declaration: ASTNode) -> str:
    """Extract the declaration title from an ASTNode."""
    call = declaration.child("call")
    if call is None:
        return "Generated"
    arguments = translator._call_arguments(call)
    if arguments and arguments[0][0] is None and arguments[0][1].kind == "Literal":
        return str(literal_value(arguments[0][1]))
    return "Generated"


def collect_declaration_metadata(
    translator: Any,
    declaration: ASTNode,
    declaration_context_fields: dict[str, set[str]],
) -> None:
    """Collect metadata from the declaration node."""
    call = declaration.child("call")
    if call is None:
        return
    allowed = declaration_context_fields.get(translator.ctx.mode, set())
    metadata: dict[str, Any] = {}
    for name, value_node in translator._call_arguments(call):
        rendered = translator.translate_expression(value_node)
        key = name or ("title" if not metadata else f"arg_{len(metadata)}")
        metadata[key] = literal_or_rendered(value_node, rendered)
        if name is not None and name not in allowed:
            translator.ctx.add_diagnostic(
                UNSUPPORTED_DECLARATION_ARG,
                f"declaration argument {name!r} is not mapped for {translator.ctx.mode}",
                Severity.ERROR if translator.strict else Severity.WARNING,
                location=value_node.loc,
            )
            translator.ctx.unsupported_declaration_args.append(name)
            if translator.strict:
                raise UnsupportedBuiltinError(name)
    translator.ctx.strategy_metadata = metadata


def literal_or_rendered(node: ASTNode, rendered: str) -> Any:
    """Return literal value if available, otherwise the rendered string."""
    import ast as pyast

    if node.kind == "Literal":
        return literal_value(node)
    if node.kind == "MemberAccessExpr":
        try:
            return pyast.literal_eval(rendered)
        except (ValueError, SyntaxError):
            return rendered
    return rendered


def contains_request_call(node: ASTNode) -> bool:
    """Check if an expression tree contains a request.security call."""
    if node.kind == "CallExpr":
        callee = node.child("callee")
        if callee is not None and member_chain(callee) == "request.security":
            return True
    for child in node.children():
        if isinstance(child, (list, tuple)):
            if any(contains_request_call(c) for c in child if hasattr(c, "kind")):
                return True
        elif hasattr(child, "kind"):
            if contains_request_call(child):
                return True
    return False


def contains_any_request_call(node: ASTNode) -> bool:
    """Check if an expression tree contains any request.* call."""
    if node.kind == "CallExpr":
        callee = node.child("callee")
        if callee is not None:
            chain = member_chain(callee)
            if chain is not None and chain.startswith("request."):
                return True
    for child in node.children():
        if isinstance(child, (list, tuple)):
            if any(contains_any_request_call(c) for c in child if hasattr(c, "kind")):
                return True
        elif hasattr(child, "kind"):
            if contains_any_request_call(child):
                return True
    return False


def is_input_call(node: ASTNode) -> bool:
    """Check if a node is an input.* function call."""
    if node.kind != "CallExpr":
        return False
    callee = node.child("callee")
    if callee is None:
        return False
    chain = member_chain(callee)
    return chain is not None and chain.startswith("input.")


def diagnose_request_security_lower_tf_safety(
    translator: Any, expression: ASTNode
) -> None:
    """Check expression safety for request.security_lower_tf captures."""
    from ast2python.diagnostics import REQUEST_SECURITY_CAPTURE_UNSAFE, Severity
    from ast2python.errors import ScopeResolutionError

    if expression.kind == "Identifier":
        name = expression.field("name")
        try:
            info = translator.ctx.resolve_var(name)
        except ScopeResolutionError:
            return
        if info is not None and info.is_series and info.declaration_kind != "input":
            if not is_lower_tf_safe_immutable_scalar_capture(info):
                translator.ctx.add_diagnostic(
                    REQUEST_SECURITY_CAPTURE_UNSAFE,
                    f"request.security_lower_tf captures mutable series '{name}'",
                    Severity.ERROR,
                    details={
                        "variable": name,
                        "kind": info.declaration_kind,
                        "capture_type": "mutable_series",
                    },
                )
    for child_node in expression.descendants():
        if child_node is not expression:
            diagnose_request_security_lower_tf_safety(translator, child_node)


def is_lower_tf_safe_immutable_scalar_capture(info: Any) -> bool:
    """Check if a variable info is a safe immutable scalar capture for lower-tf."""
    if info.declaration_kind == "input":
        return True
    if info.type_info is not None and info.type_info.qualifier in ("const", "input"):
        return True
    return False


def diagnose_request_security_captures(translator: Any, expression: ASTNode) -> None:
    """Check nested request.security calls in expression captures."""
    from ast2python.diagnostics import WARNING_NESTED_SECURITY, Severity

    if expression.kind == "CallExpr":
        callee = expression.child("callee")
        if callee is not None and member_chain(callee) == "request.security":
            nested = contains_any_request_call(expression)
            if nested:
                translator.ctx.add_diagnostic(
                    WARNING_NESTED_SECURITY,
                    "Nested request.security call detected",
                    Severity.WARNING,
                    details={"expression": str(expression)},
                )
    for child_node in expression.descendants():
        if child_node is not expression:
            diagnose_request_security_captures(translator, child_node)


def _default_for_type(pine_type: str | None) -> str:
    """Return a default Python value string for a Pine type."""
    defaults = {
        "int": "0",
        "float": "0.0",
        "bool": "False",
        "string": '""',
        "color": '"#2962FF"',
        "symbol": '""',
        "timeframe": '""',
        "session": '""',
        "time": "0",
        "source": "close",
    }
    return defaults.get(str(pine_type or ""), "0.0")


def build_input_metadata(
    declaration: ASTNode, initializer: ASTNode, py_name: str
) -> dict[str, Any]:
    """Build input metadata dict from a declaration and its input.* initializer."""
    default_value: Any = None
    default_node = None
    options: list[str] | None = None
    minval: float | None = None
    maxval: float | None = None
    step: float | None = None
    tooltip: str | None = None
    inline: str | None = None
    group: str | None = None
    field_type: str = "float"
    confirm: bool = False

    callee = initializer.child("callee")
    chain = None if callee is None else member_chain(callee)
    if chain is not None:
        field_type = chain.split(".", 1)[1]

    for arg_name, arg_node in _call_arguments(initializer):
        if arg_name == "default":
            default_node = arg_node
            break
    if default_node is not None:
        default_value = literal_value(default_node) if default_node.kind == "Literal" else None

    for arg_name, arg_node in _call_arguments(initializer):
        if arg_name == "options":
            options = (
                [literal_value(c) for c in arg_node.children() if hasattr(c, "kind") and c.kind == "Literal"]
                if arg_node.kind == "ArrayLiteral"
                else None
            )
        elif arg_name == "minval":
            minval = literal_value(arg_node) if arg_node.kind == "Literal" else None
        elif arg_name == "maxval":
            maxval = literal_value(arg_node) if arg_node.kind == "Literal" else None
        elif arg_name == "step":
            step = literal_value(arg_node) if arg_node.kind == "Literal" else None
        elif arg_name == "tooltip":
            tooltip = literal_value(arg_node) if arg_node.kind == "Literal" else None
        elif arg_name == "inline":
            inline = literal_value(arg_node) if arg_node.kind == "Literal" else None
        elif arg_name == "group":
            group = literal_value(arg_node) if arg_node.kind == "Literal" else None
        elif arg_name == "confirm":
            confirm = bool(literal_value(arg_node)) if arg_node.kind == "Literal" else False

    public = {
        "name": py_name,
        "type": field_type,
        "title": str(declaration.field("name")),
    }
    if default_value is not None:
        public["default"] = default_value
        default_python = default_value
    else:
        default_python = _default_for_type(field_type)
        public["default"] = default_python
    if options is not None:
        public["options"] = options
    if minval is not None:
        public["minval"] = minval
    if maxval is not None:
        public["maxval"] = maxval
    if step is not None:
        public["step"] = step
    if tooltip is not None:
        public["tooltip"] = tooltip
    if inline is not None:
        public["inline"] = inline
    if group is not None:
        public["group"] = group
    if confirm:
        public["confirm"] = confirm

    return {
        "default_python": default_python,
        "public": public,
        "type": field_type,
    }


def _type_ref_name(node: ASTNode) -> str | None:
    """Extract type reference name from a declaration node."""
    type_ref = node.child("type_ref")
    if type_ref is None:
        return None
    name = type_ref.field("name")
    return str(name) if isinstance(name, str) else None


def infer_type_info(translator: Any, node: ASTNode | None) -> TypeInfo:
    """Infer TypeInfo for an AST node, using translator context when needed."""
    if node is None:
        return make_type_info("object", "simple")
    if node.kind == "Literal":
        literal_type = node.field("literal_type")
        base = (
            "object"
            if literal_type == "na"
            else ("float" if literal_type == "float" else str(literal_type or "object"))
        )
        return make_type_info(base, "const", can_be_na=base != "bool")
    if node.kind == "Identifier":
        name = str(node.field("name"))
        if name in BUILTIN_SERIES:
            return make_type_info(
                {"time": "int", "time_close": "int"}.get(name, "float"),
                "series",
                is_series=True,
            )
        if name == "bar_index":
            return make_type_info("int", "series", is_series=True, can_be_na=False)
        if name == "na":
            return make_type_info("object", "const")
        try:
            info = translator.ctx.resolve_var(name)
            if info.type_info is not None:
                if info.declaration_kind == "input":
                    return make_type_info(
                        info.type_info.base_type, "input", can_be_na=info.type_info.can_be_na
                    )
                return info.type_info
            if info.type_ref in {"line", "label", "box", "table", "PineObjectId"}:
                return make_type_info("PineObjectId", info.qualifier, is_series=info.is_series)
            return make_type_info(info.type_ref, info.qualifier, is_series=info.is_series)
        except ScopeResolutionError:
            return make_type_info("object", "simple")
    if node.kind == "MemberAccessExpr":
        chain = member_chain(node)
        if chain in {
            "strategy.long",
            "strategy.short",
            "strategy.oca.cancel",
            "strategy.oca.reduce",
        }:
            return make_type_info("string", "const", can_be_na=False)
        if chain is not None and chain.startswith("syminfo."):
            return make_type_info("string", "simple", can_be_na=False)
        if chain is not None and chain.startswith((
            "barmerge.", "display.", "currency.", "location.",
            "shape.", "size.", "position.", "plot.style_",
        )):
            return make_type_info("string", "const", can_be_na=False)
        if chain is not None and chain.startswith("color."):
            return make_type_info("color", "const", can_be_na=False)
    if is_input_call(node):
        callee = node.child("callee")
        chain = None if callee is None else member_chain(callee)
        if chain is None:
            return make_type_info("object", "input")
        info_type = chain.split(".", 1)[1]
        base = {"timeframe": "string", "session": "string", "time": "int"}.get(info_type, info_type)
        return make_type_info(base, "input", can_be_na=base != "bool")
    if node.kind == "BinaryExpr":
        left = infer_type_info(translator, node.child("left"))
        right = infer_type_info(translator, node.child("right"))
        op = node.field("op")
        if op in {"and", "or", "==", "!=", ">", ">=", "<", "<="}:
            return make_type_info(
                "bool", join_qualifiers(left.qualifier, right.qualifier), can_be_na=False
            )
        base = "float" if "float" in {left.base_type, right.base_type} else left.base_type
        return make_type_info(base, join_qualifiers(left.qualifier, right.qualifier))
    if node.kind == "UnaryExpr":
        return infer_type_info(translator, node.child("operand"))
    if node.kind == "ConditionalExpr":
        condition = infer_type_info(translator, node.child("condition"))
        if_true = infer_type_info(translator, node.child("then") or node.child("if_true"))
        if_false = infer_type_info(translator, node.child("else") or node.child("if_false"))
        base = (
            "float" if "float" in {if_true.base_type, if_false.base_type} else if_true.base_type
        )
        return make_type_info(
            base,
            join_qualifiers(
                join_qualifiers(if_true.qualifier, if_false.qualifier),
                condition.qualifier,
            ),
            can_be_na=if_true.can_be_na or if_false.can_be_na,
        )
    if node.kind in ("CallExpr",):
        callee = node.child("callee")
        chain = None if callee is None else member_chain(callee)
        if chain is not None and chain == "na":
            return make_type_info("object", "const")
    return make_type_info("object", "simple")


def infer_dtype(translator: Any, node: ASTNode | None) -> str:
    """Infer the base dtype string for a node."""
    return infer_type_info(translator, node).base_type


def build_metadata(
    translator: Any, program: ASTProgram, *, title: str, module_name: str
) -> dict[str, Any]:
    """Build translation metadata dict."""
    from ast2python.version import __version__ as ast2python_version
    from ast2python.templates.module import class_name_for_mode
    from ast2python.unsupported import node_kind_counts, unsupported_node_catalog
    from ast2python.version import RUNTIME_CONTRACT_VERSION

    declaration = {
        "kind": translator.ctx.mode,
        "title": title,
        "arguments": translator.ctx.strategy_metadata,
    }
    try:
        from ast2python.diagnostics import Severity as Sev
        has_severity = True
    except ImportError:
        has_severity = False
    
    return {
        "ast2python_version": ast2python_version,
        "generator_milestone": f"v{ast2python_version}",
        "target_runtime_contract": RUNTIME_CONTRACT_VERSION,
        "pine_version": program.field("version", "language_version", default=6),
        "source_file": f"{module_name}.pine",
        "module_name": module_name,
        "compile_profile": translator.compile_profile,
        "class_name": class_name_for_mode(translator.ctx.mode),
        "declaration": declaration,
        "inputs": translator.ctx.input_metadata,
        "types": translator.ctx.type_metadata,
        "used_builtins": sorted(translator.ctx.coverage.builtins),
        "node_kind_counts": node_kind_counts(program),
        "unsupported_nodes": unsupported_node_catalog(program),
        "import_aliases": sorted(
            translator.ctx.import_aliases.values(), key=lambda item: item["alias"]
        ),
        "unsupported_declaration_args": sorted(set(translator.ctx.unsupported_declaration_args)),
        "unsafe": translator.compile_profile != "production" or not translator.parity_safe,
        "parity_safe": translator.parity_safe,
        "codegen_safe": not any(d.severity is Sev.ERROR for d in translator.ctx.diagnostics),
        "runtime_contract_safe": translator.parity_safe,
        "unsupported_features": sorted(translator.unsupported_features),
        "parity_risks": translator.parity_risks,
        "producer_metadata": program.field("producer_metadata"),
        "diagnostics": [item.to_dict() for item in translator.ctx.diagnostics],
        "source_map_file": f"{module_name}.sourcemap.json",
    }
