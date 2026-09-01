from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from ast2python.admission.ast_view import StrictASTView
from ast2python.admission.canonical import freeze_json, thaw_json
from ast2python.errors import BundleInvariantError

_FACT_FIELDS = frozenset(
    {
        "call_form",
        "classification",
        "coercions",
        "const_value",
        "declaration_target",
        "diagnostic_refs",
        "kind",
        "node_id",
        "node_kind",
        "overload_id",
        "receiver_type",
        "resolved_type",
        "scope_id",
        "semantic_rule_ids",
        "span",
        "stateful_call",
        "symbol_id",
    }
)
_CALL_FIELDS = frozenset(
    {
        "arguments",
        "call_form",
        "callee",
        "defaults_applied",
        "node_id",
        "overload_id",
        "receiver_type",
        "resolution_status",
        "return_type",
        "stateful",
        "symbol_id",
    }
)
_ARGUMENT_FIELDS = frozenset(
    {
        "actual_qualifier",
        "actual_type",
        "argument_node_id",
        "binding",
        "expected_type",
        "max_qualifier",
        "parameter_index",
        "parameter_name",
    }
)
_DEFAULT_FIELDS = frozenset(
    {
        "parameter_name",
        "parameter_index",
        "binding",
        "expected_type",
        "max_qualifier",
        "default_known",
        "default_value",
    }
)
_FACTS_ENVELOPE_FIELDS = frozenset(
    {
        "schema_id",
        "schema_version",
        "version_context",
        "version_context_ref",
        "catalog_hash",
        "facts",
        "calls",
        "diagnostics",
        "coverage",
        "content_hash",
    }
)


def _validate_default_bindings(
    defaults: list[dict[str, Any]],
    *,
    path: str,
    seen_parameter_indices: set[int],
    seen_parameter_names: set[str],
) -> tuple[Mapping[str, Any], ...]:
    for index, default in enumerate(defaults):
        item_path = f"{path}[{index}]"
        if set(default) != _DEFAULT_FIELDS:
            raise BundleInvariantError(
                "A2P_CALL_DEFAULT_FIELDS",
                "default binding fields are not exact",
                path=item_path,
            )
        parameter_index = default.get("parameter_index")
        parameter_name = default.get("parameter_name")
        if type(parameter_index) is not int or parameter_index < 0:
            raise BundleInvariantError(
                "A2P_CALL_DEFAULT_INDEX",
                "default parameter_index must be nonnegative",
                path=f"{item_path}.parameter_index",
            )
        if parameter_index in seen_parameter_indices:
            raise BundleInvariantError(
                "A2P_CALL_DEFAULT_INDEX_DUPLICATE",
                "default parameter_index must be unique within the call",
                path=f"{item_path}.parameter_index",
            )
        if not isinstance(parameter_name, str) or not parameter_name:
            raise BundleInvariantError(
                "A2P_CALL_DEFAULT_NAME",
                "default parameter_name must be non-empty",
                path=f"{item_path}.parameter_name",
            )
        if parameter_name in seen_parameter_names:
            raise BundleInvariantError(
                "A2P_CALL_DEFAULT_NAME_DUPLICATE",
                "default parameter_name must be unique within the call",
                path=f"{item_path}.parameter_name",
            )
        if default.get("binding") != "defaulted":
            raise BundleInvariantError(
                "A2P_CALL_DEFAULT_BINDING",
                "default binding must be 'defaulted'",
                path=f"{item_path}.binding",
            )
        expected_type = default.get("expected_type")
        if not isinstance(expected_type, str) or not expected_type:
            raise BundleInvariantError(
                "A2P_CALL_DEFAULT_TYPE",
                "default expected_type must be non-empty",
                path=f"{item_path}.expected_type",
            )
        if default.get("max_qualifier") not in {"const", "input", "simple", "series"}:
            raise BundleInvariantError(
                "A2P_CALL_DEFAULT_QUALIFIER",
                "default max_qualifier is invalid",
                path=f"{item_path}.max_qualifier",
            )
        default_known = default.get("default_known")
        if type(default_known) is not bool or (
            not default_known and default.get("default_value") is not None
        ):
            raise BundleInvariantError(
                "A2P_CALL_DEFAULT_VALUE",
                "unknown defaults must use null default_value",
                path=f"{item_path}.default_value",
            )
        seen_parameter_indices.add(parameter_index)
        seen_parameter_names.add(parameter_name)
    return tuple(freeze_json(defaults))


@dataclass(frozen=True, slots=True)
class FactTypeView:
    base: str
    qualifier: str
    nullable: bool

    @classmethod
    def from_fact(cls, value: Any, *, path: str) -> FactTypeView | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise BundleInvariantError(
                "A2P_FACT_TYPE", "resolved_type must be an object or null", path=path
            )
        if set(value) != {"base", "qualifier", "nullable"}:
            raise BundleInvariantError(
                "A2P_FACT_TYPE_FIELDS",
                "resolved_type must contain exactly base, qualifier and nullable",
                path=path,
            )
        base = value.get("base")
        qualifier = value.get("qualifier")
        nullable = value.get("nullable")
        if not isinstance(base, str) or not base:
            raise BundleInvariantError(
                "A2P_FACT_TYPE_BASE", "resolved type base must be non-empty", path=f"{path}.base"
            )
        if qualifier not in {"const", "input", "simple", "series"}:
            raise BundleInvariantError(
                "A2P_FACT_QUALIFIER",
                f"unknown qualifier {qualifier!r}",
                path=f"{path}.qualifier",
            )
        if type(nullable) is not bool:
            raise BundleInvariantError(
                "A2P_FACT_NULLABLE", "nullable must be boolean", path=f"{path}.nullable"
            )
        return cls(base=base, qualifier=qualifier, nullable=nullable)

    def to_dict(self) -> dict[str, Any]:
        return {"base": self.base, "qualifier": self.qualifier, "nullable": self.nullable}


@dataclass(frozen=True, slots=True)
class SemanticFactView:
    node_id: str
    node_kind: str
    classification: str
    resolved_type: FactTypeView | None
    scope_id: str
    symbol_id: str | None
    overload_id: str | None
    call_form: str | None
    receiver_type: str | None
    coercions: tuple[Any, ...]
    semantic_rule_ids: tuple[str, ...]
    stateful_call: bool
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ResolvedCallView:
    node_id: str
    callee: str
    symbol_id: str
    overload_id: str
    call_form: str
    receiver_type: str | None
    return_type: str
    stateful: bool
    arguments: tuple[Mapping[str, Any], ...]
    defaults_applied: tuple[Mapping[str, Any], ...]
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class SemanticFactsIndex:
    fact_by_node_id: Mapping[str, SemanticFactView]
    call_by_node_id: Mapping[str, ResolvedCallView]
    scope_members: Mapping[str, tuple[str, ...]]
    symbol_references: Mapping[str, tuple[str, ...]]
    overload_references: Mapping[str, tuple[str, ...]]
    semantic_rule_references: Mapping[str, tuple[str, ...]]

    @classmethod
    def build(
        cls,
        payload: Any,
        *,
        ast_view: StrictASTView,
        version_context: Mapping[str, Any],
        production: bool,
    ) -> SemanticFactsIndex:
        if not isinstance(payload, dict):
            raise BundleInvariantError(
                "A2P_FACTS_TYPE", "semantic_facts must be an object", path="$.semantic_facts"
            )
        if set(payload) != _FACTS_ENVELOPE_FIELDS:
            raise BundleInvariantError(
                "A2P_FACTS_FIELDS",
                "semantic facts envelope fields are not exact",
                path="$.semantic_facts",
                details={
                    "missing": sorted(_FACTS_ENVELOPE_FIELDS - set(payload)),
                    "extra": sorted(set(payload) - _FACTS_ENVELOPE_FIELDS),
                },
            )
        if (
            payload.get("schema_id") != "pine.semantic_facts.v1"
            or payload.get("schema_version") != "1.0.0"
        ):
            raise BundleInvariantError(
                "A2P_FACTS_SCHEMA",
                "semantic facts contract must be pine.semantic_facts.v1 / 1.0.0",
                path="$.semantic_facts",
            )
        expected_facts_version_context = {
            key: value for key, value in version_context.items() if key != "context_hash"
        }
        if payload.get("version_context") != expected_facts_version_context:
            raise BundleInvariantError(
                "A2P_FACTS_VERSION_CONTEXT",
                "semantic facts embedded version_context differs from the admitted bundle version_context",
                path="$.semantic_facts.version_context",
            )
        if payload.get("catalog_hash") != version_context.get("catalog_hash"):
            raise BundleInvariantError(
                "A2P_FACTS_CATALOG_HASH",
                "semantic facts catalog_hash differs from version_context",
                path="$.semantic_facts.catalog_hash",
            )
        if payload.get("version_context_ref") != version_context.get("context_hash"):
            raise BundleInvariantError(
                "A2P_FACTS_VERSION_REF",
                "semantic facts version_context_ref differs from version_context context_hash",
                path="$.semantic_facts.version_context_ref",
            )
        coverage = payload.get("coverage")
        if not isinstance(coverage, Mapping):
            raise BundleInvariantError(
                "A2P_FACTS_COVERAGE_TYPE",
                "coverage must be an object",
                path="$.semantic_facts.coverage",
            )
        if production:
            if coverage.get("ok") is not True:
                raise BundleInvariantError(
                    "A2P_FACTS_COVERAGE_STATUS",
                    "semantic coverage must be clean",
                    path="$.semantic_facts.coverage.ok",
                )
            for ratio_name in ("facts_ratio", "expression_type_ratio", "call_resolution_ratio"):
                if coverage.get(ratio_name) != 1.0:
                    raise BundleInvariantError(
                        "A2P_FACTS_COVERAGE_RATIO",
                        f"{ratio_name} must equal 1.0",
                        path=f"$.semantic_facts.coverage.{ratio_name}",
                    )
            if coverage.get("missing_fact_nodes") != [] or coverage.get("unresolved_calls") != []:
                raise BundleInvariantError(
                    "A2P_FACTS_COVERAGE_GAPS",
                    "coverage contains semantic gaps",
                    path="$.semantic_facts.coverage",
                )
        diagnostics = payload.get("diagnostics")
        if not isinstance(diagnostics, list):
            raise BundleInvariantError(
                "A2P_FACTS_DIAGNOSTICS",
                "semantic facts diagnostics must be an array",
                path="$.semantic_facts.diagnostics",
            )
        if production and any(
            str(item.get("severity", "")).upper() in {"ERROR", "FATAL"}
            for item in diagnostics
            if isinstance(item, Mapping)
        ):
            raise BundleInvariantError(
                "A2P_FACTS_BLOCKING_DIAGNOSTIC",
                "semantic facts contain blocking diagnostics",
                path="$.semantic_facts.diagnostics",
            )
        facts_raw = payload.get("facts")
        calls_raw = payload.get("calls")
        if not isinstance(facts_raw, list) or not isinstance(calls_raw, list):
            raise BundleInvariantError(
                "A2P_FACTS_ARRAYS",
                "semantic facts must contain facts and calls arrays",
                path="$.semantic_facts",
            )

        facts: dict[str, SemanticFactView] = {}
        scopes: defaultdict[str, list[str]] = defaultdict(list)
        symbols: defaultdict[str, list[str]] = defaultdict(list)
        overloads: defaultdict[str, list[str]] = defaultdict(list)
        rules: defaultdict[str, list[str]] = defaultdict(list)
        for index, raw in enumerate(facts_raw):
            path = f"$.semantic_facts.facts[{index}]"
            if not isinstance(raw, dict):
                raise BundleInvariantError(
                    "A2P_FACT_ROW", "semantic fact rows must be objects", path=path
                )
            if set(raw) != _FACT_FIELDS:
                raise BundleInvariantError(
                    "A2P_FACT_FIELDS",
                    "semantic fact fields are not exact",
                    path=path,
                    details={
                        "missing": sorted(_FACT_FIELDS - set(raw)),
                        "extra": sorted(set(raw) - _FACT_FIELDS),
                    },
                )
            node_id = raw.get("node_id")
            node_kind = raw.get("node_kind")
            if not isinstance(node_id, str) or not node_id:
                raise BundleInvariantError(
                    "A2P_FACT_NODE_ID", "fact node_id is required", path=f"{path}.node_id"
                )
            if node_id in facts:
                raise BundleInvariantError(
                    "A2P_FACT_DUPLICATE",
                    f"duplicate semantic fact for {node_id}",
                    path=f"{path}.node_id",
                )
            if node_id not in ast_view.nodes:
                raise BundleInvariantError(
                    "A2P_FACT_ORPHAN",
                    f"semantic fact references unknown AST node {node_id}",
                    path=f"{path}.node_id",
                )
            ast_node = ast_view.node(node_id)
            if node_kind != ast_node.kind or raw.get("kind") != ast_node.kind:
                raise BundleInvariantError(
                    "A2P_FACT_KIND",
                    "semantic fact kind differs from AST node kind",
                    path=f"{path}.node_kind",
                )
            if raw.get("span") != dict(ast_node.span):
                raise BundleInvariantError(
                    "A2P_FACT_SPAN",
                    "semantic fact span differs from AST node span",
                    path=f"{path}.span",
                )
            scope_id = raw.get("scope_id")
            if not isinstance(scope_id, str) or not scope_id.startswith("scope:"):
                raise BundleInvariantError(
                    "A2P_SCOPE_ID",
                    "scope_id must be a producer identity beginning with 'scope:'",
                    path=f"{path}.scope_id",
                )
            classification = raw.get("classification")
            if not isinstance(classification, str) or not classification:
                raise BundleInvariantError(
                    "A2P_FACT_CLASSIFICATION",
                    "fact classification is required",
                    path=f"{path}.classification",
                )
            symbol_id = raw.get("symbol_id")
            overload_id = raw.get("overload_id")
            call_form = raw.get("call_form")
            receiver_type = raw.get("receiver_type")
            if symbol_id is not None and (not isinstance(symbol_id, str) or not symbol_id):
                raise BundleInvariantError(
                    "A2P_SYMBOL_ID",
                    "symbol_id must be null or non-empty string",
                    path=f"{path}.symbol_id",
                )
            if overload_id is not None and (not isinstance(overload_id, str) or not overload_id):
                raise BundleInvariantError(
                    "A2P_OVERLOAD_ID",
                    "overload_id must be null or non-empty string",
                    path=f"{path}.overload_id",
                )
            if call_form is not None and (not isinstance(call_form, str) or not call_form):
                raise BundleInvariantError(
                    "A2P_CALL_FORM",
                    "call_form must be null or non-empty string",
                    path=f"{path}.call_form",
                )
            if receiver_type is not None and not isinstance(receiver_type, str):
                raise BundleInvariantError(
                    "A2P_RECEIVER_TYPE",
                    "receiver_type must be null or string",
                    path=f"{path}.receiver_type",
                )
            raw_rules = raw.get("semantic_rule_ids", [])
            if not isinstance(raw_rules, list) or not all(
                isinstance(item, str) and item for item in raw_rules
            ):
                raise BundleInvariantError(
                    "A2P_RULE_IDS",
                    "semantic_rule_ids must be strings",
                    path=f"{path}.semantic_rule_ids",
                )
            raw_coercions = raw.get("coercions", [])
            if not isinstance(raw_coercions, list):
                raise BundleInvariantError(
                    "A2P_COERCIONS", "coercions must be an array", path=f"{path}.coercions"
                )
            stateful = raw.get("stateful_call", False)
            if type(stateful) is not bool:
                raise BundleInvariantError(
                    "A2P_STATEFUL", "stateful_call must be boolean", path=f"{path}.stateful_call"
                )
            view = SemanticFactView(
                node_id=node_id,
                node_kind=str(node_kind),
                classification=classification,
                resolved_type=FactTypeView.from_fact(
                    raw.get("resolved_type"), path=f"{path}.resolved_type"
                ),
                scope_id=scope_id,
                symbol_id=symbol_id,
                overload_id=overload_id,
                call_form=call_form,
                receiver_type=receiver_type,
                coercions=tuple(freeze_json(raw_coercions)),
                semantic_rule_ids=tuple(raw_rules),
                stateful_call=stateful,
                raw=freeze_json(raw),
            )
            facts[node_id] = view
            scopes[scope_id].append(node_id)
            if symbol_id:
                symbols[symbol_id].append(node_id)
            if overload_id:
                overloads[overload_id].append(node_id)
            for rule_id in raw_rules:
                rules[rule_id].append(node_id)

        missing = set(ast_view.nodes) - set(facts)
        extra = set(facts) - set(ast_view.nodes)
        if missing or extra:
            raise BundleInvariantError(
                "A2P_FACT_COVERAGE",
                "semantic facts must have a one-to-one relationship with AST nodes",
                path="$.semantic_facts.facts",
                details={"missing": sorted(missing), "extra": sorted(extra)},
            )

        calls: dict[str, ResolvedCallView] = {}
        for index, raw in enumerate(calls_raw):
            path = f"$.semantic_facts.calls[{index}]"
            if not isinstance(raw, dict):
                raise BundleInvariantError("A2P_CALL_ROW", "call rows must be objects", path=path)
            if set(raw) != _CALL_FIELDS:
                raise BundleInvariantError(
                    "A2P_CALL_FIELDS",
                    "call binding fields are not exact",
                    path=path,
                    details={
                        "missing": sorted(_CALL_FIELDS - set(raw)),
                        "extra": sorted(set(raw) - _CALL_FIELDS),
                    },
                )
            node_id = raw.get("node_id")
            if not isinstance(node_id, str) or node_id not in facts:
                raise BundleInvariantError(
                    "A2P_CALL_NODE_ID", "call references unknown fact", path=f"{path}.node_id"
                )
            if node_id in calls:
                raise BundleInvariantError(
                    "A2P_CALL_DUPLICATE", "duplicate call row", path=f"{path}.node_id"
                )
            if ast_view.node(node_id).kind != "CallExpr":
                raise BundleInvariantError(
                    "A2P_CALL_KIND", "call row must reference CallExpr", path=f"{path}.node_id"
                )
            status = raw.get("resolution_status")
            if production and status != "RESOLVED":
                raise BundleInvariantError(
                    "A2P_CALL_UNRESOLVED",
                    f"production admission requires RESOLVED calls, got {status!r}",
                    path=f"{path}.resolution_status",
                )
            symbol_id = raw.get("symbol_id")
            overload_id = raw.get("overload_id")
            if production and (not isinstance(symbol_id, str) or not symbol_id):
                raise BundleInvariantError(
                    "A2P_CALL_SYMBOL_ID",
                    "resolved call is missing symbol_id",
                    path=f"{path}.symbol_id",
                )
            if production and (not isinstance(overload_id, str) or not overload_id):
                raise BundleInvariantError(
                    "A2P_CALL_OVERLOAD_ID",
                    "resolved call is missing overload_id",
                    path=f"{path}.overload_id",
                )
            if not isinstance(symbol_id, str) or not isinstance(overload_id, str):
                continue
            fact = facts[node_id]
            if fact.symbol_id != symbol_id or fact.overload_id != overload_id:
                raise BundleInvariantError(
                    "A2P_CALL_FACT_IDENTITY",
                    "call identity differs from its semantic fact",
                    path=path,
                )
            callee = raw.get("callee")
            call_form = raw.get("call_form")
            return_type = raw.get("return_type")
            stateful = raw.get("stateful")
            arguments = raw.get("arguments", [])
            defaults_applied = raw.get("defaults_applied", [])
            if not isinstance(callee, str) or not callee:
                raise BundleInvariantError(
                    "A2P_CALL_CALLEE", "callee is required", path=f"{path}.callee"
                )
            if not isinstance(call_form, str) or not call_form:
                raise BundleInvariantError(
                    "A2P_CALL_FORM", "call_form is required", path=f"{path}.call_form"
                )
            if not isinstance(return_type, str) or not return_type:
                raise BundleInvariantError(
                    "A2P_CALL_RETURN", "return_type is required", path=f"{path}.return_type"
                )
            if type(stateful) is not bool:
                raise BundleInvariantError(
                    "A2P_CALL_STATEFUL", "stateful must be boolean", path=f"{path}.stateful"
                )
            if not isinstance(arguments, list) or not all(
                isinstance(item, dict) for item in arguments
            ):
                raise BundleInvariantError(
                    "A2P_CALL_ARGUMENTS", "arguments must be objects", path=f"{path}.arguments"
                )
            if not isinstance(defaults_applied, list) or not all(
                isinstance(item, dict) for item in defaults_applied
            ):
                raise BundleInvariantError(
                    "A2P_CALL_DEFAULTS",
                    "defaults_applied must contain objects",
                    path=f"{path}.defaults_applied",
                )
            expected_argument_nodes = {
                child_id
                for child_id in ast_view.node(node_id).child_node_ids
                if ast_view.node(child_id).kind == "Argument"
            }
            seen_argument_nodes: set[str] = set()
            seen_parameter_indices: set[int] = set()
            seen_parameter_names: set[str] = set()
            for argument_index, argument in enumerate(arguments):
                argument_path = f"{path}.arguments[{argument_index}]"
                if set(argument) != _ARGUMENT_FIELDS:
                    raise BundleInvariantError(
                        "A2P_CALL_ARGUMENT_FIELDS",
                        "call argument fields are not exact",
                        path=argument_path,
                    )
                argument_node_id = argument.get("argument_node_id")
                if not isinstance(argument_node_id, str) or argument_node_id not in facts:
                    raise BundleInvariantError(
                        "A2P_CALL_ARGUMENT_NODE",
                        "argument references unknown semantic fact",
                        path=f"{argument_path}.argument_node_id",
                    )
                argument_node = ast_view.node(argument_node_id)
                if argument_node.kind != "Argument":
                    raise BundleInvariantError(
                        "A2P_CALL_ARGUMENT_KIND",
                        "argument_node_id must reference an AST Argument node",
                        path=f"{argument_path}.argument_node_id",
                    )
                if argument_node_id not in ast_view.node(node_id).child_node_ids:
                    raise BundleInvariantError(
                        "A2P_CALL_ARGUMENT_CHILD",
                        "argument_node_id must be a direct Argument child of its CallExpr",
                        path=f"{argument_path}.argument_node_id",
                    )
                if argument_node_id in seen_argument_nodes:
                    raise BundleInvariantError(
                        "A2P_CALL_ARGUMENT_NODE_DUPLICATE",
                        "argument_node_id must be unique within a call",
                        path=f"{argument_path}.argument_node_id",
                    )
                seen_argument_nodes.add(argument_node_id)
                parameter_index = argument.get("parameter_index")
                if type(parameter_index) is not int or parameter_index < 0:
                    raise BundleInvariantError(
                        "A2P_CALL_PARAMETER_INDEX",
                        "parameter_index must be a nonnegative integer",
                        path=f"{argument_path}.parameter_index",
                    )
                parameter_index_value = parameter_index
                if parameter_index_value in seen_parameter_indices:
                    raise BundleInvariantError(
                        "A2P_CALL_PARAMETER_INDEX_DUPLICATE",
                        "parameter_index must be unique within a call",
                        path=f"{argument_path}.parameter_index",
                    )
                seen_parameter_indices.add(parameter_index_value)
                parameter_name = argument.get("parameter_name")
                if not isinstance(parameter_name, str) or not parameter_name:
                    raise BundleInvariantError(
                        "A2P_CALL_PARAMETER_NAME",
                        "parameter_name must be a non-empty string",
                        path=f"{argument_path}.parameter_name",
                    )
                if parameter_name in seen_parameter_names:
                    raise BundleInvariantError(
                        "A2P_CALL_PARAMETER_NAME_DUPLICATE",
                        "parameter_name must be unique within a call",
                        path=f"{argument_path}.parameter_name",
                    )
                seen_parameter_names.add(parameter_name)
                binding = argument.get("binding")
                if not isinstance(binding, str) or binding not in {
                    "positional",
                    "named",
                    "vararg",
                }:
                    raise BundleInvariantError(
                        "A2P_CALL_ARGUMENT_BINDING",
                        "binding must be positional, named or vararg",
                        path=f"{argument_path}.binding",
                    )
                ast_argument_name = argument_node.fields.get("name")
                if (binding in {"positional", "vararg"} and ast_argument_name is not None) or (
                    binding == "named" and ast_argument_name != parameter_name
                ):
                    raise BundleInvariantError(
                        "A2P_CALL_ARGUMENT_FORM",
                        "semantic binding must agree with the AST Argument form",
                        path=f"{argument_path}.binding",
                    )
                actual_type = argument.get("actual_type")
                if not isinstance(actual_type, str) or not actual_type:
                    raise BundleInvariantError(
                        "A2P_CALL_ACTUAL_TYPE",
                        "actual_type must be a non-empty string",
                        path=f"{argument_path}.actual_type",
                    )
                actual_qualifier = argument.get("actual_qualifier")
                if not isinstance(actual_qualifier, str) or actual_qualifier not in {
                    "const",
                    "input",
                    "simple",
                    "series",
                }:
                    raise BundleInvariantError(
                        "A2P_CALL_ACTUAL_QUALIFIER",
                        "actual_qualifier must be const, input, simple or series",
                        path=f"{argument_path}.actual_qualifier",
                    )
                expected_type = argument.get("expected_type")
                if not isinstance(expected_type, str) or not expected_type:
                    raise BundleInvariantError(
                        "A2P_CALL_EXPECTED_TYPE",
                        "expected_type must be a non-empty string",
                        path=f"{argument_path}.expected_type",
                    )
                if argument.get("max_qualifier") not in {
                    "const",
                    "input",
                    "simple",
                    "series",
                }:
                    raise BundleInvariantError(
                        "A2P_CALL_MAX_QUALIFIER",
                        "max_qualifier must be const, input, simple or series",
                        path=f"{argument_path}.max_qualifier",
                    )
            if seen_argument_nodes != expected_argument_nodes:
                raise BundleInvariantError(
                    "A2P_CALL_ARGUMENT_COVERAGE",
                    "semantic arguments must cover every AST Argument child exactly once",
                    path=f"{path}.arguments",
                    details={
                        "missing": sorted(expected_argument_nodes - seen_argument_nodes),
                        "extra": sorted(seen_argument_nodes - expected_argument_nodes),
                    },
                )
            validated_defaults = _validate_default_bindings(
                defaults_applied,
                path=f"{path}.defaults_applied",
                seen_parameter_indices=seen_parameter_indices,
                seen_parameter_names=seen_parameter_names,
            )
            calls[node_id] = ResolvedCallView(
                node_id=node_id,
                callee=callee,
                symbol_id=symbol_id,
                overload_id=overload_id,
                call_form=call_form,
                receiver_type=(
                    raw.get("receiver_type") if isinstance(raw.get("receiver_type"), str) else None
                ),
                return_type=return_type,
                stateful=stateful,
                arguments=tuple(freeze_json(arguments)),
                defaults_applied=validated_defaults,
                raw=freeze_json(raw),
            )

        expected_call_nodes = {
            node_id for node_id, node in ast_view.nodes.items() if node.kind == "CallExpr"
        }
        if production and set(calls) != expected_call_nodes:
            raise BundleInvariantError(
                "A2P_CALL_COVERAGE",
                "production admission requires one resolved call row for every CallExpr",
                path="$.semantic_facts.calls",
                details={
                    "missing": sorted(expected_call_nodes - set(calls)),
                    "extra": sorted(set(calls) - expected_call_nodes),
                },
            )

        def frozen_index(source: Mapping[str, list[str]]) -> Mapping[str, tuple[str, ...]]:
            return MappingProxyType({key: tuple(values) for key, values in sorted(source.items())})

        return cls(
            fact_by_node_id=MappingProxyType(facts),
            call_by_node_id=MappingProxyType(calls),
            scope_members=frozen_index(scopes),
            symbol_references=frozen_index(symbols),
            overload_references=frozen_index(overloads),
            semantic_rule_references=frozen_index(rules),
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "fact_count": len(self.fact_by_node_id),
            "call_count": len(self.call_by_node_id),
            "scope_count": len(self.scope_members),
            "symbol_reference_count": len(self.symbol_references),
            "overload_reference_count": len(self.overload_references),
            "semantic_rule_count": len(self.semantic_rule_references),
        }

    def fact_payload(self, node_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], thaw_json(self.fact_by_node_id[node_id].raw))
