from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from ast2python.admission.ast_view import StrictASTView
from ast2python.admission.canonical import (
    canonical_json_bytes,
    enforce_generic_limits,
    freeze_json,
    load_bundle_input,
    thaw_json,
)
from ast2python.admission.facts import FactTypeView, SemanticFactsIndex
from ast2python.admission.invariants import (
    _validate_release_axes,
    validate_bundle_envelope,
    validate_consumer_contract,
    validate_diagnostics,
    validate_source_descriptor,
    validate_version_context,
)
from ast2python.admission.limits import AdmissionLimits
from ast2python.admission.producer_identity import validate_producer_identity
from ast2python.errors import BundleAdmissionError
from ast2python.mode import CompilationMode
from tests.conftest import load_bundle


def assert_code(code: str, func, *args, **kwargs) -> None:
    with pytest.raises(BundleAdmissionError) as caught:
        func(*args, **kwargs)
    assert caught.value.finding.code == code
    assert caught.value.finding.to_dict()["code"] == code


def test_canonical_input_error_paths(tmp_path: Path) -> None:
    limits = AdmissionLimits()
    assert_code("A2P_JSON_NOT_CANONICALIZABLE", canonical_json_bytes, {"x": object()})
    assert_code("A2P_JSON_ENCODING", load_bundle_input, b"\xff", limits)
    assert_code("A2P_JSON_INVALID", load_bundle_input, b"{", limits)
    assert_code("A2P_BUNDLE_ROOT_TYPE", load_bundle_input, b"[]", limits)
    assert_code("A2P_BUNDLE_SOURCE_TYPE", load_bundle_input, 1, limits)
    assert_code("A2P_JSON_KEY_TYPE", load_bundle_input, {1: "x"}, limits)
    assert_code("A2P_JSON_VALUE_TYPE", load_bundle_input, {"x": object()}, limits)
    assert_code("A2P_JSON_NONFINITE", load_bundle_input, {"x": float("inf")}, limits)

    missing = tmp_path / "missing.json"
    assert_code("A2P_BUNDLE_PATH", load_bundle_input, missing, limits)
    assert_code("A2P_BUNDLE_PATH", load_bundle_input, tmp_path, limits)

    oversized = tmp_path / "large.json"
    oversized.write_text('{"x":"' + "x" * 200 + '"}', encoding="utf-8")
    assert_code(
        "A2P_BUNDLE_TOO_LARGE",
        load_bundle_input,
        oversized,
        AdmissionLimits(max_bundle_bytes=100),
    )
    assert_code(
        "A2P_BUNDLE_TOO_LARGE",
        load_bundle_input,
        {"x": "x" * 200},
        AdmissionLimits(max_bundle_bytes=100),
    )

    value, raw = load_bundle_input(bytearray(b'{"x":1}'), limits)
    assert value == {"x": 1}
    assert raw == b'{"x":1}'
    value, raw = load_bundle_input(memoryview(b'{"x":1}'), limits)
    assert value == {"x": 1}
    assert raw == b'{"x":1}'


def test_generic_limits_and_freeze_thaw() -> None:
    assert_code(
        "A2P_STRING_TOO_LONG",
        enforce_generic_limits,
        {"x": "12345"},
        AdmissionLimits(max_string_length=4),
    )
    assert_code(
        "A2P_STRING_TOO_LONG",
        enforce_generic_limits,
        {"12345": 1},
        AdmissionLimits(max_string_length=4),
    )
    frozen = freeze_json({"a": [1, {"b": 2}]})
    assert thaw_json(frozen) == {"a": [1, {"b": 2}]}
    assert freeze_json("x") == "x"
    assert thaw_json("x") == "x"


def test_limit_validation_and_mode() -> None:
    assert_code("A2P_LIMIT_INVALID", AdmissionLimits, max_calls=0)
    assert_code("A2P_LIMIT_ABOVE_ABSOLUTE", AdmissionLimits, max_calls=999_999_999)
    assert CompilationMode.normalize("analysis") is CompilationMode.ANALYSIS
    with pytest.raises(ValueError, match="unsupported compilation mode"):
        CompilationMode.normalize("wrong")


def test_producer_identity_validation() -> None:
    valid = {"name": "pine2ast", "version": "5.0.0rc6", "commit": None}
    identity = validate_producer_identity(valid)
    assert identity.commit_bound is False
    assert identity.to_dict()["commit_bound"] is False
    assert_code("A2P_PRODUCER_TYPE", validate_producer_identity, None)
    assert_code("A2P_PRODUCER_FIELDS", validate_producer_identity, {"name": "pine2ast"})
    assert_code("A2P_PRODUCER_NAME", validate_producer_identity, {**valid, "name": "x"})
    assert_code("A2P_PRODUCER_VERSION", validate_producer_identity, {**valid, "version": "x"})
    assert_code("A2P_PRODUCER_COMMIT", validate_producer_identity, {**valid, "commit": "BAD"})
    bound = validate_producer_identity({**valid, "commit": "a" * 40})
    assert bound.commit_bound is True


def test_bundle_envelope_error_paths() -> None:
    bundle = load_bundle(6)
    limits = AdmissionLimits()
    invalid = deepcopy(bundle)
    invalid.pop("source")
    assert_code("A2P_BUNDLE_FIELDS", validate_bundle_envelope, invalid, limits)
    invalid = deepcopy(bundle)
    invalid["content_hash"] = 3
    assert_code("A2P_BUNDLE_CONTENT_HASH", validate_bundle_envelope, invalid, limits)
    invalid = deepcopy(bundle)
    invalid["node_index"] = {}
    assert_code("A2P_NODE_INDEX_TYPE", validate_bundle_envelope, invalid, limits)
    assert_code(
        "A2P_AST_NODE_LIMIT",
        validate_bundle_envelope,
        bundle,
        AdmissionLimits(max_ast_nodes=1),
    )
    invalid = deepcopy(bundle)
    invalid["semantic_facts"] = []
    assert_code("A2P_FACTS_TYPE", validate_bundle_envelope, invalid, limits)
    invalid = deepcopy(bundle)
    invalid["semantic_facts"]["facts"] = {}
    assert_code("A2P_FACTS_ARRAYS", validate_bundle_envelope, invalid, limits)
    assert_code(
        "A2P_FACT_LIMIT",
        validate_bundle_envelope,
        bundle,
        AdmissionLimits(max_facts=1),
    )
    assert_code(
        "A2P_CALL_LIMIT",
        validate_bundle_envelope,
        load_bundle(4),
        AdmissionLimits(max_calls=1),
    )
    invalid = deepcopy(bundle)
    invalid["diagnostics"] = {}
    assert_code("A2P_DIAGNOSTICS_TYPE", validate_bundle_envelope, invalid, limits)
    invalid = deepcopy(bundle)
    invalid["diagnostics"] = [None, None]
    assert_code(
        "A2P_DIAGNOSTIC_LIMIT",
        validate_bundle_envelope,
        invalid,
        AdmissionLimits(max_diagnostics=1),
    )
    invalid = deepcopy(bundle)
    invalid["linked_artifacts"] = []
    assert_code("A2P_LINKED_TYPE", validate_bundle_envelope, invalid, limits)
    assert_code(
        "A2P_LINKED_LIMIT",
        validate_bundle_envelope,
        bundle,
        AdmissionLimits(max_linked_artifacts=1),
    )


@pytest.mark.parametrize("count", [0, 3])
def test_release_axis_accepts_complete_nonnegative_pass_counts(count: int) -> None:
    release_axes = deepcopy(load_bundle(6)["release_axes"])
    release_axes["method_receiver_typed"] = {
        "status": "PASS",
        "verified": count,
        "total": count,
    }

    _validate_release_axes(release_axes)


@pytest.mark.parametrize(
    ("verified", "total"),
    [
        (1, 2),
        (2, 1),
        (-1, -1),
        (True, True),
    ],
)
def test_release_axis_rejects_incomplete_or_malformed_pass_counts(
    verified: object, total: object
) -> None:
    release_axes = deepcopy(load_bundle(6)["release_axes"])
    release_axes["method_receiver_typed"] = {
        "status": "PASS",
        "verified": verified,
        "total": total,
    }

    assert_code("A2P_RELEASE_AXIS_NOT_PASSING", _validate_release_axes, release_axes)


def test_release_axis_accepts_not_applicable_only_for_zero_counts() -> None:
    release_axes = deepcopy(load_bundle(6)["release_axes"])
    release_axes["method_receiver_typed"] = {
        "status": "NOT_APPLICABLE",
        "verified": 0,
        "total": 0,
    }

    _validate_release_axes(release_axes)


@pytest.mark.parametrize(
    ("status", "verified", "total"),
    [
        ("FAIL", 0, 0),
        ("NOT_RUN", 0, 0),
        ("NOT_APPLICABLE", 1, 1),
        ("NOT_APPLICABLE", 0, 1),
        ("NOT_APPLICABLE", -1, -1),
        ("NOT_APPLICABLE", False, False),
    ],
)
def test_release_axis_rejects_nonpassing_or_malformed_not_applicable_results(
    status: str, verified: object, total: object
) -> None:
    release_axes = deepcopy(load_bundle(6)["release_axes"])
    release_axes["method_receiver_typed"] = {
        "status": status,
        "verified": verified,
        "total": total,
    }

    assert_code("A2P_RELEASE_AXIS_NOT_PASSING", _validate_release_axes, release_axes)


def test_version_context_error_paths() -> None:
    value = load_bundle(6)["version_context"]
    assert validate_version_context(value).to_dict() == value
    assert_code("A2P_VERSION_CONTEXT_TYPE", validate_version_context, None)
    invalid = deepcopy(value)
    invalid["x"] = 1
    assert_code("A2P_VERSION_CONTEXT_FIELDS", validate_version_context, invalid)
    invalid = deepcopy(value)
    invalid["pine_version"] = 7
    assert_code("A2P_PINE_VERSION", validate_version_context, invalid)
    invalid = deepcopy(value)
    invalid["origin"] = "x"
    assert_code("A2P_VERSION_ORIGIN", validate_version_context, invalid)
    invalid = deepcopy(value)
    invalid["annotation_span"] = 1
    assert_code("A2P_SOURCE_SPAN_FIELDS", validate_version_context, invalid)
    invalid = deepcopy(value)
    invalid["annotation_span"] = None
    assert_code("A2P_VERSION_ANNOTATION_SPAN", validate_version_context, invalid)
    v1 = deepcopy(load_bundle(1)["version_context"])
    v1["annotation_span"] = {}
    assert_code("A2P_VERSION_DEFAULT_SPAN", validate_version_context, v1)
    invalid = deepcopy(value)
    invalid["spec_snapshot_ref"] = ""
    assert_code("A2P_SPEC_SNAPSHOT", validate_version_context, invalid)
    invalid = deepcopy(value)
    invalid["catalog_hash"] = "x"
    assert_code("A2P_VERSION_HASH", validate_version_context, invalid)


def test_consumer_source_and_diagnostics_validation() -> None:
    bundle = load_bundle(6)
    contract = bundle["consumer_contract"]
    limits = AdmissionLimits()
    assert validate_consumer_contract(contract, limits)
    assert_code("A2P_CONSUMER_CONTRACT_TYPE", validate_consumer_contract, None, limits)
    invalid = deepcopy(contract)
    invalid["x"] = 1
    assert_code("A2P_CONSUMER_CONTRACT_FIELDS", validate_consumer_contract, invalid, limits)
    invalid = deepcopy(contract)
    invalid["consumer"] = "x"
    assert_code("A2P_CONSUMER_NAME", validate_consumer_contract, invalid, limits)
    invalid = deepcopy(contract)
    invalid["minimum_consumer_version"] = "x"
    assert_code("A2P_CONSUMER_VERSION", validate_consumer_contract, invalid, limits)
    invalid = deepcopy(contract)
    invalid["required_capabilities"] = [1]
    assert_code("A2P_CAPABILITIES_TYPE", validate_consumer_contract, invalid, limits)
    assert_code(
        "A2P_DEPENDENCY_LIMIT",
        validate_consumer_contract,
        contract,
        AdmissionLimits(max_dependency_count=1),
    )
    invalid = deepcopy(contract)
    invalid["required_capabilities"] *= 2
    assert_code("A2P_CAPABILITY_DUPLICATE", validate_consumer_contract, invalid, limits)
    invalid = deepcopy(contract)
    invalid["required_capabilities"] = ["unknown"]
    assert_code("A2P_CAPABILITY_SET", validate_consumer_contract, invalid, limits)

    source = bundle["source"]
    assert validate_source_descriptor(source) == source
    assert_code("A2P_SOURCE_TYPE", validate_source_descriptor, None)
    invalid = deepcopy(source)
    invalid["x"] = 1
    assert_code("A2P_SOURCE_FIELDS", validate_source_descriptor, invalid)
    invalid = deepcopy(source)
    invalid["name"] = ""
    assert_code("A2P_SOURCE_NAME", validate_source_descriptor, invalid)
    invalid = deepcopy(source)
    invalid["encoding"] = "latin-1"
    assert_code("A2P_SOURCE_ENCODING", validate_source_descriptor, invalid)
    invalid = deepcopy(source)
    invalid["byte_length"] = -1
    assert_code("A2P_SOURCE_LENGTH", validate_source_descriptor, invalid)
    invalid = deepcopy(source)
    invalid["source_hash"] = "x"
    assert_code("A2P_SOURCE_HASH", validate_source_descriptor, invalid)

    assert_code("A2P_DIAGNOSTICS_TYPE", validate_diagnostics, {}, CompilationMode.PRODUCTION)
    assert_code("A2P_DIAGNOSTIC_ROW", validate_diagnostics, [1], CompilationMode.PRODUCTION)
    assert validate_diagnostics([{"severity": "warning"}], CompilationMode.PRODUCTION)


def _ast_view(bundle: dict) -> StrictASTView:
    return StrictASTView.build(
        bundle["ast"], bundle["node_index"], version_context=bundle["version_context"]
    )


def test_ast_view_error_paths() -> None:
    bundle = load_bundle(6)
    assert_code(
        "A2P_AST_ROOT",
        StrictASTView.build,
        {},
        bundle["node_index"],
        version_context=bundle["version_context"],
    )
    invalid = deepcopy(bundle["ast"])
    invalid["language"] = "x"
    assert_code(
        "A2P_AST_LANGUAGE",
        StrictASTView.build,
        invalid,
        bundle["node_index"],
        version_context=bundle["version_context"],
    )
    invalid = deepcopy(bundle["ast"])
    invalid["schema_version"] = "1"
    assert_code(
        "A2P_AST_SCHEMA",
        StrictASTView.build,
        invalid,
        bundle["node_index"],
        version_context=bundle["version_context"],
    )
    invalid = deepcopy(bundle["ast"])
    invalid["version_context"] = {}
    assert_code(
        "A2P_AST_VERSION_CONTEXT",
        StrictASTView.build,
        invalid,
        bundle["node_index"],
        version_context=bundle["version_context"],
    )
    assert_code(
        "A2P_NODE_INDEX_TYPE",
        StrictASTView.build,
        bundle["ast"],
        {},
        version_context=bundle["version_context"],
    )
    assert_code(
        "A2P_NODE_INDEX_CARDINALITY",
        StrictASTView.build,
        bundle["ast"],
        bundle["node_index"][:-1],
        version_context=bundle["version_context"],
    )
    rows = deepcopy(bundle["node_index"])
    rows[0] = 1
    assert_code(
        "A2P_NODE_INDEX_ROW",
        StrictASTView.build,
        bundle["ast"],
        rows,
        version_context=bundle["version_context"],
    )
    rows = deepcopy(bundle["node_index"])
    rows[0]["x"] = 1
    assert_code(
        "A2P_NODE_INDEX_FIELDS",
        StrictASTView.build,
        bundle["ast"],
        rows,
        version_context=bundle["version_context"],
    )
    rows = deepcopy(bundle["node_index"])
    rows[0]["ordinal"] = 2
    assert_code(
        "A2P_NODE_INDEX_ORDINAL",
        StrictASTView.build,
        bundle["ast"],
        rows,
        version_context=bundle["version_context"],
    )
    rows = deepcopy(bundle["node_index"])
    rows[0]["node_id"] = ""
    assert_code(
        "A2P_NODE_ID",
        StrictASTView.build,
        bundle["ast"],
        rows,
        version_context=bundle["version_context"],
    )
    rows = deepcopy(bundle["node_index"])
    rows[1]["node_id"] = rows[0]["node_id"]
    assert_code(
        "A2P_NODE_ID_DUPLICATE",
        StrictASTView.build,
        bundle["ast"],
        rows,
        version_context=bundle["version_context"],
    )
    rows = deepcopy(bundle["node_index"])
    rows[0]["kind"] = "Wrong"
    assert_code(
        "A2P_NODE_INDEX_MISMATCH",
        StrictASTView.build,
        bundle["ast"],
        rows,
        version_context=bundle["version_context"],
    )
    view = _ast_view(bundle)
    assert view.node(view.root_node_id).to_dict()["kind"] == "Program"
    with pytest.raises(KeyError, match="unknown AST node_id"):
        view.node("missing")


def test_fact_type_validation() -> None:
    assert FactTypeView.from_fact(None, path="$") is None
    view = FactTypeView.from_fact(
        {"base": "float", "qualifier": "series", "nullable": True}, path="$"
    )
    assert view is not None and view.to_dict()["base"] == "float"
    assert_code("A2P_FACT_TYPE", FactTypeView.from_fact, [], path="$")
    assert_code("A2P_FACT_TYPE_FIELDS", FactTypeView.from_fact, {"base": "x"}, path="$")
    assert_code(
        "A2P_FACT_TYPE_BASE",
        FactTypeView.from_fact,
        {"base": "", "qualifier": "const", "nullable": False},
        path="$",
    )
    assert_code(
        "A2P_FACT_QUALIFIER",
        FactTypeView.from_fact,
        {"base": "x", "qualifier": "bad", "nullable": False},
        path="$",
    )
    assert_code(
        "A2P_FACT_NULLABLE",
        FactTypeView.from_fact,
        {"base": "x", "qualifier": "const", "nullable": 0},
        path="$",
    )


def test_semantic_fact_error_paths() -> None:
    bundle = load_bundle(6)
    ast = _ast_view(bundle)
    ctx = bundle["version_context"]
    payload = bundle["semantic_facts"]
    assert_code(
        "A2P_FACTS_TYPE",
        SemanticFactsIndex.build,
        [],
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["x"] = 1
    assert_code(
        "A2P_FACTS_FIELDS",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["schema_version"] = "x"
    assert_code(
        "A2P_FACTS_SCHEMA",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["catalog_hash"] = "x"
    assert_code(
        "A2P_FACTS_CATALOG_HASH",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["version_context_ref"] = "x"
    assert_code(
        "A2P_FACTS_VERSION_REF",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["coverage"] = []
    assert_code(
        "A2P_FACTS_COVERAGE_TYPE",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["coverage"]["ok"] = False
    assert_code(
        "A2P_FACTS_COVERAGE_STATUS",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["coverage"]["facts_ratio"] = 0.5
    assert_code(
        "A2P_FACTS_COVERAGE_RATIO",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["coverage"]["missing_fact_nodes"] = ["x"]
    assert_code(
        "A2P_FACTS_COVERAGE_GAPS",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["diagnostics"] = {}
    assert_code(
        "A2P_FACTS_DIAGNOSTICS",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["diagnostics"] = [{"severity": "ERROR"}]
    assert_code(
        "A2P_FACTS_BLOCKING_DIAGNOSTIC",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["facts"] = {}
    assert_code(
        "A2P_FACTS_ARRAYS",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )

    fact_cases = [
        ("A2P_FACT_ROW", lambda row: 1),
        ("A2P_FACT_FIELDS", lambda row: {**row, "x": 1}),
        ("A2P_FACT_NODE_ID", lambda row: {**row, "node_id": ""}),
        ("A2P_FACT_ORPHAN", lambda row: {**row, "node_id": "missing"}),
        ("A2P_FACT_KIND", lambda row: {**row, "node_kind": "Wrong"}),
        ("A2P_FACT_SPAN", lambda row: {**row, "span": {}}),
        ("A2P_FACT_CLASSIFICATION", lambda row: {**row, "classification": ""}),
        ("A2P_SCOPE_ID", lambda row: {**row, "scope_id": ""}),
        ("A2P_SYMBOL_ID", lambda row: {**row, "symbol_id": 1}),
        ("A2P_OVERLOAD_ID", lambda row: {**row, "overload_id": 1}),
        ("A2P_CALL_FORM", lambda row: {**row, "call_form": 1}),
        ("A2P_RECEIVER_TYPE", lambda row: {**row, "receiver_type": 1}),
        ("A2P_RULE_IDS", lambda row: {**row, "semantic_rule_ids": [1]}),
        ("A2P_COERCIONS", lambda row: {**row, "coercions": {}}),
        ("A2P_STATEFUL", lambda row: {**row, "stateful_call": 1}),
    ]
    for code, mutate in fact_cases:
        invalid = deepcopy(payload)
        invalid["facts"][0] = mutate(invalid["facts"][0])
        assert_code(
            code,
            SemanticFactsIndex.build,
            invalid,
            ast_view=ast,
            version_context=ctx,
            production=True,
        )

    invalid = deepcopy(payload)
    invalid["facts"].append(deepcopy(invalid["facts"][0]))
    assert_code(
        "A2P_FACT_DUPLICATE",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )

    call_cases = [
        ("A2P_CALL_ROW", lambda row: 1),
        ("A2P_CALL_FIELDS", lambda row: {**row, "x": 1}),
        ("A2P_CALL_NODE_ID", lambda row: {**row, "node_id": "missing"}),
        ("A2P_CALL_UNRESOLVED", lambda row: {**row, "resolution_status": "UNRESOLVED"}),
        ("A2P_CALL_SYMBOL_ID", lambda row: {**row, "symbol_id": None}),
        ("A2P_CALL_OVERLOAD_ID", lambda row: {**row, "overload_id": None}),
        ("A2P_CALL_FACT_IDENTITY", lambda row: {**row, "symbol_id": "wrong"}),
        ("A2P_CALL_CALLEE", lambda row: {**row, "callee": ""}),
        ("A2P_CALL_FORM", lambda row: {**row, "call_form": ""}),
        ("A2P_CALL_RETURN", lambda row: {**row, "return_type": ""}),
        ("A2P_CALL_STATEFUL", lambda row: {**row, "stateful": 1}),
        ("A2P_CALL_ARGUMENTS", lambda row: {**row, "arguments": [1]}),
    ]
    for code, mutate in call_cases:
        invalid = deepcopy(payload)
        invalid["calls"][0] = mutate(invalid["calls"][0])
        assert_code(
            code,
            SemanticFactsIndex.build,
            invalid,
            ast_view=ast,
            version_context=ctx,
            production=True,
        )

    invalid = deepcopy(payload)
    invalid["calls"].append(deepcopy(invalid["calls"][0]))
    assert_code(
        "A2P_CALL_DUPLICATE",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["calls"][0]["arguments"][0]["x"] = 1
    assert_code(
        "A2P_CALL_ARGUMENT_FIELDS",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["calls"][0]["arguments"][0]["argument_node_id"] = "missing"
    assert_code(
        "A2P_CALL_ARGUMENT_NODE",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )
    invalid = deepcopy(payload)
    invalid["calls"][0]["arguments"][0]["parameter_index"] = -1
    assert_code(
        "A2P_CALL_PARAMETER_INDEX",
        SemanticFactsIndex.build,
        invalid,
        ast_view=ast,
        version_context=ctx,
        production=True,
    )

    index = SemanticFactsIndex.build(payload, ast_view=ast, version_context=ctx, production=True)
    assert index.fact_payload(ast.root_node_id)["node_id"] == ast.root_node_id
