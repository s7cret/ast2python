"""Materialize admitted producer facts, not source-text substitutions.

Metadata is embedded literally in the emitted module and therefore covered by
its sealed code hash. Display titles never serve as parameter identities. This
module does not evaluate Python or reparse Pine; all names and arguments come
from the producer's checked IR bindings.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn

from ast2python.admission.canonical import thaw_json
from ast2python.errors import BundleInvariantError
from ast2python.lowering.model import LoweringPlan

_SOURCE_NAMES = frozenset(
    {"open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4", "hlcc4"}
)
_INPUT_KINDS = frozenset(
    {
        "bool",
        "int",
        "float",
        "string",
        "time",
        "price",
        "symbol",
        "timeframe",
        "session",
        "color",
        "source",
    }
)
_INPUT_FIELDS = {
    "defval": "default",
    "title": "title",
    "minval": "minimum",
    "maxval": "maximum",
    "step": "step",
    "options": "options",
    "group": "group",
    "inline": "inline",
    "tooltip": "tooltip",
    "confirm": "confirm",
    "display": "display",
    "active": "active",
}
_LEGACY_TYPES = {
    "bool": "bool",
    "integer": "int",
    "float": "float",
    "string": "string",
    "symbol": "symbol",
    "resolution": "timeframe",
    "session": "session",
    "source": "source",
    "time": "time",
    "color": "color",
}


class ScriptMetadata:
    def __init__(self, plan: LoweringPlan) -> None:
        self.plan = plan
        self.attrs = {key: thaw_json(node.attributes) for key, node in plan.nodes.items()}
        self.declarations = {
            row["symbol_id"]: key
            for key, row in self.attrs.items()
            if row["ast_kind"] == "VarDeclaration" and row.get("symbol_id")
        }
        self.aliases = {}
        for key, row in self.attrs.items():
            children = self.roles(key).get("initializer", ())
            if row["ast_kind"] == "VarDeclaration" and len(children) == 1:
                self.aliases[children[0]] = row["fields"]["name"]
        self.inputs: dict[str, dict[str, Any]] = {}
        self.input_ids: dict[str, str] = {}
        self.declaration: dict[str, Any] = {}
        for key in plan.ordered_ir_ids:
            row = self.attrs[key]
            if row["ast_kind"] == "DeclarationStatement":
                calls = self.roles(key).get("call", ())
                if len(calls) != 1:
                    self.fail("script declaration is incomplete", key)
                self.declaration = {
                    "script_type": row["fields"]["script_type"],
                    "arguments": self.arguments(calls[0]),
                }
            if row["ast_kind"] != "CallExpr":
                continue
            call = row.get("call", {})
            symbol = call.get("symbol_id", "")
            if symbol != "pine:function:input" and not symbol.startswith("pine:function:input."):
                continue
            arguments = self.arguments(key, allow_source=True)
            if "defval" not in arguments:
                self.fail("input lacks an admitted default", key)
            unknown = set(arguments) - (set(_INPUT_FIELDS) | {"type"})
            if unknown:
                self.fail(f"input has unsupported metadata: {sorted(unknown)}", key)
            kind = (
                symbol.removeprefix("pine:function:input.")
                if symbol != "pine:function:input"
                else None
            )
            if kind is None:
                if "type" in arguments:
                    legacy = arguments["type"]
                    if not isinstance(legacy, str) or not legacy.startswith("input."):
                        self.fail("legacy input type must be an admitted input constant", key)
                    kind = _LEGACY_TYPES.get(legacy.removeprefix("input."))
                else:
                    default = arguments["defval"]
                    kind = {bool: "bool", int: "int", float: "float", str: "string"}.get(
                        type(default)
                    )
                    # A built-in series is symbolic only in a source default.
                    arg_ir = self.argument_nodes(key)["defval"]
                    if self.source_name(arg_ir) is not None:
                        kind = "source"
            if kind not in _INPUT_KINDS:
                self.fail("input kind is not supported by the admitted input contract", key)
            input_id = f"input:{plan.nodes[key].source.node_id}"
            descriptor: dict[str, Any] = {"input_id": input_id, "kind": kind}
            descriptor.update(
                {
                    _INPUT_FIELDS[name]: value
                    for name, value in arguments.items()
                    if name in _INPUT_FIELDS
                }
            )
            if key in self.aliases:
                descriptor["alias"] = self.aliases[key]
            descriptor["source_span"] = thaw_json(plan.nodes[key].source.span)
            self.inputs[input_id] = descriptor
            self.input_ids[key] = input_id

    def roles(self, key: str) -> Mapping[str, list[str]]:
        return self.attrs[key].get("child_roles", {})

    def fail(self, message: str, key: str) -> NoReturn:
        raise BundleInvariantError(
            "A2P_STATIC_METADATA",
            message,
            details={"ir_id": key, "source_span": thaw_json(self.plan.nodes[key].source.span)},
        )

    def source_name(self, key: str) -> str | None:
        symbol = self.attrs[key].get("symbol_id")
        if isinstance(symbol, str) and symbol.startswith("pine:variable:"):
            name = symbol.removeprefix("pine:variable:")
            return name if name in _SOURCE_NAMES else None
        return None

    def argument_nodes(self, key: str) -> dict[str, str]:
        call = self.attrs[key].get("call", {})
        argument_nodes = {
            self.plan.nodes[child].source.node_id: child
            for child in self.roles(key).get("arguments", ())
        }
        result = {}
        for binding in sorted(call.get("arguments", ()), key=lambda item: item["parameter_index"]):
            arg = argument_nodes.get(binding["argument_node_id"])
            children = () if arg is None else self.roles(arg).get("value", ())
            if len(children) != 1:
                self.fail("metadata argument lacks its exact producer binding", key)
            result[binding["parameter_name"]] = children[0]
        return result

    def arguments(self, key: str, *, allow_source: bool = False) -> dict[str, Any]:
        return {
            name: self.constant(child, allow_source=allow_source and name == "defval")
            for name, child in self.argument_nodes(key).items()
        }

    def constant(
        self, key: str, *, allow_source: bool = False, visiting: frozenset[str] = frozenset()
    ) -> Any:
        if key in visiting:
            self.fail("cyclic constant metadata", key)
        row = self.attrs[key]
        fields = row.get("fields", {})
        kind = row["ast_kind"]
        if allow_source and self.source_name(key) is not None:
            return self.source_name(key)
        if kind == "Literal":
            return fields["value"]
        if kind == "TupleExpr":
            return [
                self.constant(child, visiting=visiting | {key})
                for child in self.roles(key).get("elements", ())
            ]
        symbol = row.get("symbol_id")
        if (
            kind in {"Identifier", "MemberAccessExpr"}
            and isinstance(symbol, str)
            and symbol.startswith(
                (
                    "pine:variable:strategy.",
                    "pine:variable:input.",
                    "pine:variable:display.",
                    "pine:variable:currency.",
                )
            )
        ):
            return symbol.removeprefix("pine:variable:")
        # Facts are version-exact and sealed by the admitted consumer bundle.
        result_type = self.plan.nodes[key].result_type
        if (
            result_type is not None
            and result_type.qualifier == "const"
            and row.get("const_value") is not None
        ):
            return row["const_value"]
        symbol = row.get("symbol_id")
        if kind in {"Identifier", "MemberAccessExpr"} and isinstance(symbol, str):
            declaration = self.declarations.get(symbol)
            if declaration is not None:
                children = self.roles(declaration).get("initializer", ())
                if len(children) == 1:
                    return self.constant(
                        children[0],
                        allow_source=allow_source,
                        visiting=visiting | {key, declaration},
                    )
            if symbol.startswith(
                (
                    "pine:variable:strategy.",
                    "pine:variable:input.",
                    "pine:variable:display.",
                    "pine:variable:currency.",
                )
            ):
                # These remain symbolic. Their owner resolves them rather than
                # guessing a numeric enum value inside the compiler.
                return symbol.removeprefix("pine:variable:")
        self.fail("metadata expression has no admitted constant value", key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": "ast2python.script_metadata.v1",
            "pine_version": self.plan.pine_version,
            "source_hash": self.plan.source_hash,
            "declaration": self.declaration,
            "inputs": self.inputs,
        }
