from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from ast2python.admission.canonical import freeze_json
from ast2python.admission.limits import AdmissionLimits
from ast2python.errors import BundleInvariantError, BundleLimitError
from ast2python.mode import CompilationMode
from ast2python.version import CONSUMER_BUNDLE_SCHEMA_ID, CONSUMER_BUNDLE_SCHEMA_VERSION

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

ALLOWED_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_id",
        "schema_version",
        "producer",
        "source",
        "version_context",
        "ast",
        "semantic_facts",
        "node_index",
        "diagnostics",
        "release_axes",
        "artifacts",
        "linked_artifacts",
        "consumer_contract",
        "content_hash",
    }
)

REQUIRED_CONSUMER_CAPABILITIES = frozenset(
    {
        "pine_version_context_v1",
        "pine_ast_v2",
        "pine_semantic_facts_v1",
        "resolved_symbol_identity",
        "resolved_overload_identity",
        "source_span_identity",
    }
)

_SOURCE_SPAN_FIELDS = frozenset(
    {
        "start_offset",
        "end_offset",
        "start_line",
        "start_col",
        "end_line",
        "end_col",
    }
)

_RELEASE_COMPILER_AXES = frozenset(
    {
        "name_registered",
        "overload_resolved",
        "qualifier_enforced",
        "arguments_bound",
        "method_receiver_typed",
        "version_availability_enforced",
        "bundle_fact_coverage_complete",
    }
)


def _validate_release_axes(value: Any) -> None:
    expected = _RELEASE_COMPILER_AXES | {"tradingview_compile_oracle"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise BundleInvariantError(
            "A2P_RELEASE_AXES_FIELDS",
            "release axes are not exact",
            path="$.release_axes",
        )
    for name in sorted(_RELEASE_COMPILER_AXES):
        axis = value.get(name)
        if not isinstance(axis, Mapping) or set(axis) != {"status", "verified", "total"}:
            raise BundleInvariantError(
                "A2P_RELEASE_AXIS_FIELDS",
                "compiler release axis fields are not exact",
                path=f"$.release_axes.{name}",
            )
        status = axis.get("status")
        verified = axis.get("verified")
        total = axis.get("total")
        valid_counts = type(verified) is int and type(total) is int
        valid_pass = valid_counts and status == "PASS" and verified >= 0 and verified == total
        valid_not_applicable = (
            valid_counts and status == "NOT_APPLICABLE" and verified == total == 0
        )
        if not (valid_pass or valid_not_applicable):
            raise BundleInvariantError(
                "A2P_RELEASE_AXIS_NOT_PASSING",
                "compiler release axis must be a valid PASS or NOT_APPLICABLE result",
                path=f"$.release_axes.{name}",
            )
    oracle = value.get("tradingview_compile_oracle")
    if oracle != {"status": "NOT_RUN", "evidence_id": None}:
        raise BundleInvariantError(
            "A2P_RELEASE_ORACLE_SELF_CERTIFIED",
            "consumer bundle cannot self-certify TradingView oracle parity",
            path="$.release_axes.tradingview_compile_oracle",
        )


def validate_source_span(value: Any, *, path: str) -> Mapping[str, int]:
    if not isinstance(value, Mapping) or set(value) != _SOURCE_SPAN_FIELDS:
        raise BundleInvariantError(
            "A2P_SOURCE_SPAN_FIELDS",
            "source span fields are not exact",
            path=path,
        )
    coordinates = {name: value.get(name) for name in _SOURCE_SPAN_FIELDS}
    if any(type(item) is not int for item in coordinates.values()):
        raise BundleInvariantError(
            "A2P_SOURCE_SPAN_TYPE",
            "source span coordinates must be integers",
            path=path,
        )
    typed_coordinates = cast(dict[str, int], coordinates)
    if (
        typed_coordinates["start_offset"] < 0
        or typed_coordinates["end_offset"] < typed_coordinates["start_offset"]
        or typed_coordinates["start_line"] < 1
        or typed_coordinates["end_line"] < typed_coordinates["start_line"]
        or typed_coordinates["start_col"] < 1
        or typed_coordinates["end_col"] < 1
        or (
            typed_coordinates["start_line"] == typed_coordinates["end_line"]
            and typed_coordinates["end_col"] < typed_coordinates["start_col"]
        )
    ):
        raise BundleInvariantError(
            "A2P_SOURCE_SPAN_ORDER",
            "source span coordinates have invalid ordering",
            path=path,
        )
    return cast(Mapping[str, int], freeze_json(dict(typed_coordinates)))


@dataclass(frozen=True, slots=True)
class PineVersionIdentity:
    pine_version: int
    origin: str
    annotation_span: Mapping[str, Any] | None
    spec_snapshot_ref: str
    catalog_hash: str
    context_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pine_version": self.pine_version,
            "origin": self.origin,
            "annotation_span": None if self.annotation_span is None else dict(self.annotation_span),
            "spec_snapshot_ref": self.spec_snapshot_ref,
            "catalog_hash": self.catalog_hash,
            "context_hash": self.context_hash,
        }


def validate_bundle_envelope(bundle: Mapping[str, Any], limits: AdmissionLimits) -> None:
    fields = set(bundle)
    if fields != ALLOWED_TOP_LEVEL_FIELDS:
        raise BundleInvariantError(
            "A2P_BUNDLE_FIELDS",
            "consumer bundle top-level fields are not exact",
            details={
                "missing": sorted(ALLOWED_TOP_LEVEL_FIELDS - fields),
                "extra": sorted(fields - ALLOWED_TOP_LEVEL_FIELDS),
            },
        )
    if bundle.get("schema_id") != CONSUMER_BUNDLE_SCHEMA_ID:
        raise BundleInvariantError(
            "A2P_BUNDLE_SCHEMA_ID",
            f"schema_id must be {CONSUMER_BUNDLE_SCHEMA_ID}",
            path="$.schema_id",
        )
    if bundle.get("schema_version") != CONSUMER_BUNDLE_SCHEMA_VERSION:
        raise BundleInvariantError(
            "A2P_BUNDLE_SCHEMA_VERSION",
            f"schema_version must be {CONSUMER_BUNDLE_SCHEMA_VERSION}",
            path="$.schema_version",
        )
    content_hash = bundle.get("content_hash")
    if not isinstance(content_hash, str) or _HASH_RE.fullmatch(content_hash) is None:
        raise BundleInvariantError(
            "A2P_BUNDLE_CONTENT_HASH",
            "content_hash must be a lowercase sha256 identity",
            path="$.content_hash",
        )

    node_index = bundle.get("node_index")
    facts = bundle.get("semantic_facts")
    diagnostics = bundle.get("diagnostics")
    linked = bundle.get("linked_artifacts")
    if not isinstance(node_index, list):
        raise BundleInvariantError(
            "A2P_NODE_INDEX_TYPE", "node_index must be an array", path="$.node_index"
        )
    if len(node_index) > limits.max_ast_nodes:
        raise BundleLimitError(
            "A2P_AST_NODE_LIMIT",
            f"AST node count {len(node_index)} exceeds {limits.max_ast_nodes}",
            path="$.node_index",
        )
    if not isinstance(facts, Mapping):
        raise BundleInvariantError(
            "A2P_FACTS_TYPE", "semantic_facts must be an object", path="$.semantic_facts"
        )
    facts_rows = facts.get("facts")
    calls_rows = facts.get("calls")
    if not isinstance(facts_rows, list) or not isinstance(calls_rows, list):
        raise BundleInvariantError(
            "A2P_FACTS_ARRAYS", "facts and calls must be arrays", path="$.semantic_facts"
        )
    if len(facts_rows) > limits.max_facts:
        raise BundleLimitError(
            "A2P_FACT_LIMIT",
            f"fact count {len(facts_rows)} exceeds {limits.max_facts}",
            path="$.semantic_facts.facts",
        )
    if len(calls_rows) > limits.max_calls:
        raise BundleLimitError(
            "A2P_CALL_LIMIT",
            f"call count {len(calls_rows)} exceeds {limits.max_calls}",
            path="$.semantic_facts.calls",
        )
    if not isinstance(diagnostics, list):
        raise BundleInvariantError(
            "A2P_DIAGNOSTICS_TYPE", "diagnostics must be an array", path="$.diagnostics"
        )
    if len(diagnostics) > limits.max_diagnostics:
        raise BundleLimitError(
            "A2P_DIAGNOSTIC_LIMIT",
            f"diagnostic count {len(diagnostics)} exceeds {limits.max_diagnostics}",
            path="$.diagnostics",
        )
    if not isinstance(linked, Mapping):
        raise BundleInvariantError(
            "A2P_LINKED_TYPE", "linked_artifacts must be an object", path="$.linked_artifacts"
        )
    if len(linked) > limits.max_linked_artifacts:
        raise BundleLimitError(
            "A2P_LINKED_LIMIT",
            f"linked artifact count {len(linked)} exceeds {limits.max_linked_artifacts}",
            path="$.linked_artifacts",
        )
    _validate_release_axes(bundle.get("release_axes"))


def validate_version_context(value: Any) -> PineVersionIdentity:
    if not isinstance(value, Mapping):
        raise BundleInvariantError(
            "A2P_VERSION_CONTEXT_TYPE",
            "version_context must be an object",
            path="$.version_context",
        )
    expected = {
        "pine_version",
        "origin",
        "annotation_span",
        "spec_snapshot_ref",
        "catalog_hash",
        "context_hash",
    }
    if set(value) != expected:
        raise BundleInvariantError(
            "A2P_VERSION_CONTEXT_FIELDS",
            "version_context fields are not exact",
            path="$.version_context",
            details={
                "missing": sorted(expected - set(value)),
                "extra": sorted(set(value) - expected),
            },
        )
    version = value.get("pine_version")
    if type(version) is not int or version not in {1, 2, 3, 4, 5, 6}:
        raise BundleInvariantError(
            "A2P_PINE_VERSION",
            "pine_version must be an integer from 1 through 6",
            path="$.version_context.pine_version",
        )
    origin = value.get("origin")
    if origin not in {"compiler_annotation", "tradingview_default_v1"}:
        raise BundleInvariantError(
            "A2P_VERSION_ORIGIN",
            f"unsupported version origin {origin!r}",
            path="$.version_context.origin",
        )
    annotation_span = value.get("annotation_span")
    if version == 1 and origin == "tradingview_default_v1" and annotation_span is not None:
        raise BundleInvariantError(
            "A2P_VERSION_DEFAULT_SPAN",
            "default Pine v1 must not claim a compiler-annotation span",
            path="$.version_context.annotation_span",
        )
    if origin == "compiler_annotation" and annotation_span is None:
        raise BundleInvariantError(
            "A2P_VERSION_ANNOTATION_SPAN",
            "compiler-annotation origin requires annotation_span",
            path="$.version_context.annotation_span",
        )
    if annotation_span is not None:
        annotation_span = validate_source_span(
            annotation_span,
            path="$.version_context.annotation_span",
        )
    spec = value.get("spec_snapshot_ref")
    if not isinstance(spec, str) or not spec:
        raise BundleInvariantError(
            "A2P_SPEC_SNAPSHOT",
            "spec_snapshot_ref must be non-empty",
            path="$.version_context.spec_snapshot_ref",
        )
    catalog_hash = value.get("catalog_hash")
    context_hash = value.get("context_hash")
    for name, item in (("catalog_hash", catalog_hash), ("context_hash", context_hash)):
        if not isinstance(item, str) or _HASH_RE.fullmatch(item) is None:
            raise BundleInvariantError(
                "A2P_VERSION_HASH",
                f"{name} must be a lowercase sha256 identity",
                path=f"$.version_context.{name}",
            )
    assert isinstance(catalog_hash, str)
    assert isinstance(context_hash, str)
    return PineVersionIdentity(
        pine_version=version,
        origin=origin,
        annotation_span=annotation_span,
        spec_snapshot_ref=spec,
        catalog_hash=catalog_hash,
        context_hash=context_hash,
    )


def validate_consumer_contract(value: Any, limits: AdmissionLimits) -> frozenset[str]:
    if not isinstance(value, Mapping):
        raise BundleInvariantError(
            "A2P_CONSUMER_CONTRACT_TYPE",
            "consumer_contract must be an object",
            path="$.consumer_contract",
        )
    if set(value) != {"consumer", "minimum_consumer_version", "required_capabilities"}:
        raise BundleInvariantError(
            "A2P_CONSUMER_CONTRACT_FIELDS",
            "consumer_contract fields are not exact",
            path="$.consumer_contract",
        )
    if value.get("consumer") != "ast2python":
        raise BundleInvariantError(
            "A2P_CONSUMER_NAME",
            "consumer must be 'ast2python'",
            path="$.consumer_contract.consumer",
        )
    if value.get("minimum_consumer_version") != "5.0.0rc6":
        raise BundleInvariantError(
            "A2P_CONSUMER_VERSION",
            "minimum_consumer_version must be 5.0.0rc6",
            path="$.consumer_contract.minimum_consumer_version",
        )
    capabilities = value.get("required_capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) and item for item in capabilities
    ):
        raise BundleInvariantError(
            "A2P_CAPABILITIES_TYPE",
            "required_capabilities must be non-empty strings",
            path="$.consumer_contract.required_capabilities",
        )
    if len(capabilities) > limits.max_dependency_count:
        raise BundleLimitError(
            "A2P_DEPENDENCY_LIMIT",
            f"capability count {len(capabilities)} exceeds {limits.max_dependency_count}",
            path="$.consumer_contract.required_capabilities",
        )
    if len(capabilities) != len(set(capabilities)):
        raise BundleInvariantError(
            "A2P_CAPABILITY_DUPLICATE",
            "required_capabilities must be unique",
            path="$.consumer_contract.required_capabilities",
        )
    actual = frozenset(capabilities)
    unknown = actual - REQUIRED_CONSUMER_CAPABILITIES
    missing = REQUIRED_CONSUMER_CAPABILITIES - actual
    if unknown or missing:
        raise BundleInvariantError(
            "A2P_CAPABILITY_SET",
            "consumer capability set is not exact",
            path="$.consumer_contract.required_capabilities",
            details={"unknown": sorted(unknown), "missing": sorted(missing)},
        )
    return actual


def validate_source_descriptor(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BundleInvariantError("A2P_SOURCE_TYPE", "source must be an object", path="$.source")
    if set(value) != {"name", "encoding", "byte_length", "source_hash"}:
        raise BundleInvariantError(
            "A2P_SOURCE_FIELDS", "source descriptor fields are not exact", path="$.source"
        )
    name = value.get("name")
    encoding = value.get("encoding")
    byte_length = value.get("byte_length")
    source_hash = value.get("source_hash")
    if not isinstance(name, str) or not name:
        raise BundleInvariantError(
            "A2P_SOURCE_NAME", "source name is required", path="$.source.name"
        )
    if encoding != "utf-8":
        raise BundleInvariantError(
            "A2P_SOURCE_ENCODING", "source encoding must be utf-8", path="$.source.encoding"
        )
    if type(byte_length) is not int or byte_length < 0:
        raise BundleInvariantError(
            "A2P_SOURCE_LENGTH",
            "source byte_length must be a nonnegative integer",
            path="$.source.byte_length",
        )
    if not isinstance(source_hash, str) or _HASH_RE.fullmatch(source_hash) is None:
        raise BundleInvariantError(
            "A2P_SOURCE_HASH", "source_hash must be sha256", path="$.source.source_hash"
        )
    return dict(value)


def validate_diagnostics(value: Any, mode: CompilationMode) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise BundleInvariantError(
            "A2P_DIAGNOSTICS_TYPE", "diagnostics must be an array", path="$.diagnostics"
        )
    blocking: list[int] = []
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise BundleInvariantError(
                "A2P_DIAGNOSTIC_ROW",
                "diagnostic rows must be objects",
                path=f"$.diagnostics[{index}]",
            )
        severity = str(item.get("severity", "")).upper()
        if severity in {"ERROR", "FATAL"}:
            blocking.append(index)
        result.append(item)
    if mode is CompilationMode.PRODUCTION and blocking:
        raise BundleInvariantError(
            "A2P_BLOCKING_DIAGNOSTICS",
            "production admission rejects ERROR/FATAL frontend diagnostics",
            path="$.diagnostics",
            details={"indexes": blocking},
        )
    return tuple(result)
