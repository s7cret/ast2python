from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ast2python.admission.canonical import freeze_json, thaw_json
from ast2python.admission.invariants import validate_source_span
from ast2python.errors import BundleInvariantError

_FORBIDDEN_NODE_ALIAS_FIELDS = frozenset({"type", "loc", "children"})

_ANNOTATION_KINDS = frozenset(
    {
        "VERSION",
        "DESCRIPTION",
        "FUNCTION",
        "PARAM",
        "RETURNS",
        "TYPE",
        "FIELD",
        "ENUM",
        "VARIABLE",
        "STRATEGY_ALERT_MESSAGE",
        "REGION_START",
        "REGION_END",
        "UNKNOWN",
    }
)


def _is_ast_node(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("kind"), str)
        and value["kind"] not in _ANNOTATION_KINDS
    )


def _iter_ast_nodes(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if _is_ast_node(value):
            yield value
        for child in value.values():
            yield from _iter_ast_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_ast_nodes(child)


def _direct_children(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if _is_ast_node(value):
            yield value
            return
        for child in value.values():
            yield from _direct_children(child)
    elif isinstance(value, list):
        for child in value:
            yield from _direct_children(child)


@dataclass(frozen=True, slots=True)
class StrictASTNode:
    node_id: str
    kind: str
    span: Mapping[str, Any]
    fields: Mapping[str, Any]
    child_node_ids: tuple[str, ...]
    child_roles: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "child_roles",
            MappingProxyType(
                {role: tuple(node_ids) for role, node_ids in self.child_roles.items()}
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "span": thaw_json(self.span),
            "fields": thaw_json(self.fields),
            "child_node_ids": list(self.child_node_ids),
            "child_roles": {role: list(node_ids) for role, node_ids in self.child_roles.items()},
        }


@dataclass(frozen=True, slots=True)
class StrictASTView:
    root_node_id: str
    nodes: Mapping[str, StrictASTNode]
    ordered_node_ids: tuple[str, ...]

    @property
    def node_by_id(self) -> Mapping[str, StrictASTNode]:
        return self.nodes

    @property
    def children_by_node_id(self) -> Mapping[str, tuple[str, ...]]:
        return MappingProxyType(
            {node_id: node.child_node_ids for node_id, node in self.nodes.items()}
        )

    @property
    def child_roles_by_node_id(self) -> Mapping[str, Mapping[str, tuple[str, ...]]]:
        return MappingProxyType({node_id: node.child_roles for node_id, node in self.nodes.items()})

    @classmethod
    def build(
        cls,
        ast: Any,
        node_index: Any,
        *,
        version_context: Mapping[str, Any],
    ) -> StrictASTView:
        if not isinstance(ast, dict) or ast.get("kind") != "Program":
            raise BundleInvariantError(
                "A2P_AST_ROOT",
                "bundle.ast must be an exact Program object; wrappers are forbidden",
                path="$.ast",
            )
        if ast.get("language") != "pine":
            raise BundleInvariantError(
                "A2P_AST_LANGUAGE", "AST language must be 'pine'", path="$.ast.language"
            )
        if ast.get("schema_version") != "2.0":
            raise BundleInvariantError(
                "A2P_AST_SCHEMA",
                "AST schema_version must be exactly '2.0'",
                path="$.ast.schema_version",
            )
        ast_context = ast.get("version_context")
        expected_ast_context = {
            key: value for key, value in version_context.items() if key != "context_hash"
        }
        if ast_context != expected_ast_context:
            raise BundleInvariantError(
                "A2P_AST_VERSION_CONTEXT",
                "AST version_context differs from the hashless bundle version identity",
                path="$.ast.version_context",
            )
        if not isinstance(node_index, list):
            raise BundleInvariantError(
                "A2P_NODE_INDEX_TYPE", "node_index must be an array", path="$.node_index"
            )

        raw_nodes = list(_iter_ast_nodes(ast))
        if len(raw_nodes) != len(node_index):
            raise BundleInvariantError(
                "A2P_NODE_INDEX_CARDINALITY",
                "node_index cardinality differs from the AST node set",
                path="$.node_index",
                details={"ast_nodes": len(raw_nodes), "index_rows": len(node_index)},
            )

        def signature(kind: Any, span: Any, *, path: str) -> tuple[str, str]:
            import json

            if not isinstance(kind, str) or not kind:
                raise BundleInvariantError(
                    "A2P_AST_NODE_KIND",
                    "AST node kind must be a non-empty string",
                    path=f"{path}.kind",
                )
            checked_span = validate_source_span(span, path=f"{path}.span")
            return kind, json.dumps(
                dict(checked_span),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )

        raw_by_signature: dict[tuple[str, str], dict[str, Any]] = {}
        for raw_node_index, raw_node in enumerate(raw_nodes):
            aliases = _FORBIDDEN_NODE_ALIAS_FIELDS & set(raw_node)
            if aliases:
                raise BundleInvariantError(
                    "A2P_AST_ALIAS_FIELD",
                    "tolerant AST alias fields are forbidden",
                    path=f"$.ast.nodes[{raw_node_index}]",
                    details={"fields": sorted(aliases)},
                )
            sig = signature(
                raw_node.get("kind"),
                raw_node.get("span"),
                path=f"$.ast.nodes[{raw_node_index}]",
            )
            if sig in raw_by_signature:
                raise BundleInvariantError(
                    "A2P_AST_NODE_IDENTITY_AMBIGUOUS",
                    "consumer bundle lacks enough identity to distinguish two AST nodes with the same kind/span",
                    path="$.ast",
                    details={"kind": sig[0], "span": raw_node.get("span")},
                )
            raw_by_signature[sig] = raw_node

        object_to_id: dict[int, str] = {}
        ordered_ids: list[str] = []
        rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        seen_ids: set[str] = set()
        seen_signatures: set[tuple[str, str]] = set()
        for ordinal, raw_row in enumerate(node_index):
            if not isinstance(raw_row, dict):
                raise BundleInvariantError(
                    "A2P_NODE_INDEX_ROW",
                    "node_index rows must be objects",
                    path=f"$.node_index[{ordinal}]",
                )
            if set(raw_row) != {"ordinal", "node_id", "kind", "span"}:
                raise BundleInvariantError(
                    "A2P_NODE_INDEX_FIELDS",
                    "node_index row has unexpected fields",
                    path=f"$.node_index[{ordinal}]",
                )
            if raw_row.get("ordinal") != ordinal or type(raw_row.get("ordinal")) is not int:
                raise BundleInvariantError(
                    "A2P_NODE_INDEX_ORDINAL",
                    "node_index ordinals must be contiguous integers starting at zero",
                    path=f"$.node_index[{ordinal}].ordinal",
                )
            node_id = raw_row.get("node_id")
            if not isinstance(node_id, str) or not node_id:
                raise BundleInvariantError(
                    "A2P_NODE_ID",
                    "node_id must be a non-empty string",
                    path=f"$.node_index[{ordinal}].node_id",
                )
            if node_id in seen_ids:
                raise BundleInvariantError(
                    "A2P_NODE_ID_DUPLICATE",
                    f"duplicate node_id {node_id!r}",
                    path=f"$.node_index[{ordinal}].node_id",
                )
            seen_ids.add(node_id)
            sig = signature(
                raw_row.get("kind"),
                raw_row.get("span"),
                path=f"$.node_index[{ordinal}]",
            )
            if sig in seen_signatures:
                raise BundleInvariantError(
                    "A2P_NODE_INDEX_IDENTITY_AMBIGUOUS",
                    "node_index contains duplicate kind/span identity",
                    path=f"$.node_index[{ordinal}]",
                )
            seen_signatures.add(sig)
            matched_node = raw_by_signature.get(sig)
            if matched_node is None:
                raise BundleInvariantError(
                    "A2P_NODE_INDEX_MISMATCH",
                    "node_index row has no matching AST node",
                    path=f"$.node_index[{ordinal}]",
                )
            object_to_id[id(matched_node)] = node_id
            ordered_ids.append(node_id)
            rows.append((matched_node, raw_row))

        if seen_signatures != set(raw_by_signature):
            raise BundleInvariantError(
                "A2P_NODE_INDEX_MISMATCH",
                "AST contains nodes absent from node_index",
                path="$.node_index",
            )
        root_node_id = object_to_id.get(id(ast))
        if root_node_id is None:
            raise BundleInvariantError(
                "A2P_NODE_INDEX_ROOT",
                "the Program root is absent from node_index",
                path="$.node_index",
            )
        if not ordered_ids or ordered_ids[0] != root_node_id:
            raise BundleInvariantError(
                "A2P_NODE_INDEX_ROOT_ORDER",
                "node_index ordinal zero must identify the Program root",
                path="$.node_index[0]",
            )

        node_views: dict[str, StrictASTNode] = {}
        for raw_node, raw_row in rows:
            node_id = str(raw_row["node_id"])
            child_ids: list[str] = []
            child_roles: dict[str, tuple[str, ...]] = {}
            for key, value in raw_node.items():
                if key in {"kind", "span"}:
                    continue
                role_ids: list[str] = []
                for child in _direct_children(value):
                    child_id = object_to_id.get(id(child))
                    if child_id is None:
                        raise BundleInvariantError(
                            "A2P_AST_CHILD_ID",
                            "direct AST child is absent from node_index",
                            path=f"$.ast[{node_id}].{key}",
                        )
                    child_ids.append(child_id)
                    role_ids.append(child_id)
                if role_ids:
                    child_roles[key] = tuple(role_ids)
            fields = {key: value for key, value in raw_node.items() if key not in {"kind", "span"}}
            node_views[node_id] = StrictASTNode(
                node_id=node_id,
                kind=str(raw_node["kind"]),
                span=freeze_json(raw_node["span"]),
                fields=freeze_json(fields),
                child_node_ids=tuple(child_ids),
                child_roles=MappingProxyType(child_roles),
            )

        return cls(
            root_node_id=root_node_id,
            nodes=MappingProxyType(node_views),
            ordered_node_ids=tuple(ordered_ids),
        )

    def node(self, node_id: str) -> StrictASTNode:
        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"unknown AST node_id: {node_id}") from exc

    def to_summary(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for node in self.nodes.values():
            kinds[node.kind] = kinds.get(node.kind, 0) + 1
        return {
            "root_node_id": self.root_node_id,
            "node_count": len(self.nodes),
            "kind_counts": dict(sorted(kinds.items())),
        }
