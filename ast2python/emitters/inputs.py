"""Pine input call emitters and metadata helpers."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ast2python.errors import UnsupportedBuiltinError

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTNode


INPUT_CALLS = {
    "input.int",
    "input.float",
    "input.bool",
    "input.string",
    "input.timeframe",
    "input.session",
    "input.source",
    "input.time",
    "input.symbol",
}


class PineInputEmitter:
    """Lower Pine input-family calls through the owning translator."""

    def __init__(self, translator: Any) -> None:
        self.translator = translator

    def is_input_call(self, node: ASTNode) -> bool:
        callee = node.child("callee")
        return (
            node.kind == "CallExpr"
            and callee is not None
            and self.translator.member_chain(callee) in INPUT_CALLS
        )

    def translate_runtime_lookup(self, node: ASTNode) -> str:
        translator = self.translator
        arguments = translator._call_arguments(node)
        if not arguments:
            raise UnsupportedBuiltinError("input.* requires a default value")
        default_node = arguments[0][1]
        if default_node.kind == "Literal":
            return repr(default_node.field("value"))
        return translator.translate_expression(default_node)

    def build_metadata(
        self, declaration: ASTNode, initializer: ASTNode, py_name: str
    ) -> dict[str, Any]:
        translator = self.translator
        callee = initializer.child("callee")
        chain = None if callee is None else translator.member_chain(callee)
        if chain is None:
            raise UnsupportedBuiltinError("input declaration is missing a valid callee")
        info_type = chain.split(".", 1)[1]
        args = translator._call_arguments(initializer)
        default_node = args[0][1]
        default_rendered = translator.translate_expression(default_node)
        default_value = (
            default_node.field("value")
            if default_node.kind == "Literal"
            else default_rendered
        )
        metadata = {
            "pine_name": declaration.field("name"),
            "py_name": py_name,
            "type": {
                "timeframe": "string",
                "session": "string",
                "time": "int",
                "symbol": "string",
            }.get(info_type, info_type),
            "qualifier": "input",
            "default": default_value,
            "title": None,
            "minval": None,
            "maxval": None,
            "step": None,
            "options": None,
            "group": None,
            "inline": None,
            "tooltip": None,
            "confirm": False,
            "display": "all",
            "active": True,
            "source_map": declaration.loc.source_map if declaration.loc else None,
        }
        positional_meta = ["title"]
        for index, (name, value) in enumerate(args[1:]):
            key = name or (positional_meta[index] if index < len(positional_meta) else None)
            if key in {
                "title",
                "minval",
                "maxval",
                "step",
                "options",
                "group",
                "inline",
                "tooltip",
                "confirm",
                "display",
                "active",
                "defval",
            }:
                if key == "defval":
                    continue
                rendered = translator.translate_expression(value)
                metadata[key] = translator._literal_or_rendered(value, rendered)
        public_meta = dict(metadata)
        return {
            "type": metadata["type"],
            "default_python": (
                repr(default_value) if default_node.kind == "Literal" else default_rendered
            ),
            "public": public_meta,
        }
