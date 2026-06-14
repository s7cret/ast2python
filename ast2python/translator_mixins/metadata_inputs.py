"""Legacy input metadata helper retained for compatibility."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ast2python.translator_mixins.metadata_declarations import call_arguments
from ast2python.translator_support import literal_value, member_chain

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTNode


def _default_for_type(pine_type: str | None) -> str:
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
    default_value: Any = None
    default_node = None
    options: list[str] | None = None
    minval: float | None = None
    maxval: float | None = None
    step: float | None = None
    tooltip: str | None = None
    inline: str | None = None
    group: str | None = None
    field_type = "float"
    confirm = False

    callee = initializer.child("callee")
    chain = None if callee is None else member_chain(callee)
    if chain is not None:
        field_type = chain.split(".", 1)[1]

    for index, (arg_name, arg_node) in enumerate(call_arguments(initializer)):
        if arg_name == "default" or (arg_name is None and index == 0):
            default_node = arg_node
            break
    if default_node is not None:
        default_value = literal_value(default_node) if default_node.kind == "Literal" else None

    for arg_name, arg_node in call_arguments(initializer):
        if arg_name == "options":
            options = (
                [
                    literal_value(c)
                    for c in arg_node.children("elements", "items")
                    if c.kind == "Literal"
                ]
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

    default_python = default_value if default_value is not None else _default_for_type(field_type)
    public: dict[str, Any] = {
        "name": py_name,
        "type": field_type,
        "title": str(declaration.field("name")),
        "default": default_python,
    }
    for key, value in {
        "options": options,
        "minval": minval,
        "maxval": maxval,
        "step": step,
        "tooltip": tooltip,
        "inline": inline,
        "group": group,
    }.items():
        if value is not None:
            public[key] = value
    if confirm:
        public["confirm"] = confirm
    return {"default_python": default_python, "public": public, "type": field_type}
