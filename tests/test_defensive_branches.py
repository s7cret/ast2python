from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from ast2python import CompilationMode, admit_consumer_bundle, inspect_consumer_bundle
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
    validate_consumer_contract,
    validate_diagnostics,
    validate_source_descriptor,
    validate_version_context,
)
from ast2python.admission.limits import AdmissionLimits
from ast2python.admission.producer_identity import validate_producer_identity
from ast2python.errors import BundleAdmissionError
from ast2python.mode import CompilationMode as Mode
from tests.conftest import load_bundle


def valid_parts():
    bundle = load_bundle(6)
    ast = StrictASTView.build(
        bundle["ast"], bundle["node_index"], version_context=bundle["version_context"]
    )
    return bundle, ast


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.__setitem__("ast", []),
        lambda b: b["ast"].__setitem__("kind", "NotProgram"),
        lambda b: b["ast"].__setitem__("language", "other"),
        lambda b: b["ast"].__setitem__("schema_version", "1.0"),
        lambda b: b["ast"]["version_context"].__setitem__("pine_version", 5),
        lambda b: b.__setitem__("node_index", {}),
        lambda b: b["node_index"].pop(),
        lambda b: b["node_index"].__setitem__(0, "bad"),
        lambda b: b["node_index"][0].__setitem__("extra", 1),
        lambda b: b["node_index"][0].__setitem__("ordinal", 99),
        lambda b: b["node_index"][0].__setitem__("node_id", ""),
        lambda b: b["node_index"][1].__setitem__("node_id", b["node_index"][0]["node_id"]),
        lambda b: b["node_index"][0].__setitem__("kind", "Other"),
        lambda b: b["node_index"][0].__setitem__("span", {"bad": True}),
    ],
)
def test_ast_view_rejects_malformed_shapes(mutate) -> None:
    bundle = load_bundle(6)
    mutate(bundle)
    with pytest.raises(BundleAdmissionError):
        StrictASTView.build(
            bundle.get("ast"), bundle.get("node_index"), version_context=bundle["version_context"]
        )


def test_ast_view_helpers() -> None:
    bundle, ast = valid_parts()
    root = ast.node(ast.root_node_id)
    assert root.to_dict()["kind"] == "Program"
    assert ast.to_summary()["node_count"] == len(bundle["node_index"])
    with pytest.raises(KeyError):
        ast.node("missing")


def test_ast_view_rejects_ambiguous_kind_span() -> None:
    bundle = load_bundle(6)
    # Duplicate one leaf node and its matching index row. The AST and index
    # cardinalities stay equal, so the dedicated kind/span ambiguity guard runs.
    duplicate = deepcopy(bundle["ast"]["declaration"]["call"]["callee"])
    bundle["ast"]["items"].append(duplicate)
    source_row = next(
        row
        for row in bundle["node_index"]
        if row["kind"] == duplicate["kind"] and row["span"] == duplicate["span"]
    )
    extra_row = deepcopy(source_row)
    extra_row["ordinal"] = len(bundle["node_index"])
    extra_row["node_id"] = "new"
    bundle["node_index"].append(extra_row)
    with pytest.raises(BundleAdmissionError, match="AMBIGUOUS"):
        StrictASTView.build(
            bundle["ast"], bundle["node_index"], version_context=bundle["version_context"]
        )


def test_canonical_loader_error_paths(tmp_path: Path) -> None:
    limits = AdmissionLimits(max_bundle_bytes=500, max_string_length=5, max_json_depth=4)
    with pytest.raises(BundleAdmissionError, match="A2P_JSON_ENCODING"):
        load_bundle_input(b"\xff", limits)
    with pytest.raises(BundleAdmissionError, match="A2P_JSON_INVALID"):
        load_bundle_input(b"{", limits)
    with pytest.raises(BundleAdmissionError, match="A2P_BUNDLE_ROOT_TYPE"):
        load_bundle_input(b"[]", limits)
    with pytest.raises(BundleAdmissionError, match="A2P_BUNDLE_SOURCE_TYPE"):
        load_bundle_input(123, limits)  # type: ignore[arg-type]
    with pytest.raises(BundleAdmissionError, match="A2P_JSON_KEY_TYPE"):
        load_bundle_input({1: "x"}, limits)  # type: ignore[dict-item]
    with pytest.raises(BundleAdmissionError, match="A2P_JSON_VALUE_TYPE"):
        load_bundle_input({"x": object()}, limits)
    with pytest.raises(BundleAdmissionError, match="A2P_JSON_NONFINITE"):
        load_bundle_input({"x": float("inf")}, limits)
    missing = tmp_path / "missing.json"
    with pytest.raises(BundleAdmissionError, match="A2P_BUNDLE_PATH"):
        load_bundle_input(missing, limits)
    large = tmp_path / "large.json"
    large.write_bytes(b"x" * 501)
    with pytest.raises(BundleAdmissionError, match="A2P_BUNDLE_TOO_LARGE"):
        load_bundle_input(large, limits)
    with pytest.raises(BundleAdmissionError, match="A2P_JSON_NOT_CANONICALIZABLE"):
        canonical_json_bytes({"x": object()})


def test_generic_limits_and_freezing() -> None:
    with pytest.raises(BundleAdmissionError, match="A2P_STRING_TOO_LONG"):
        enforce_generic_limits({"key": "123456"}, AdmissionLimits(max_string_length=5))
    with pytest.raises(BundleAdmissionError, match="A2P_STRING_TOO_LONG"):
        enforce_generic_limits({"123456": "x"}, AdmissionLimits(max_string_length=5))
    frozen = freeze_json({"a": [1, {"b": 2}]})
    assert thaw_json(frozen) == {"a": [1, {"b": 2}]}


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"name": "bad", "version": "5.0.0rc6", "commit": None},
        {"name": "pine2ast", "version": "bad", "commit": None},
        {"name": "pine2ast", "version": "5.0.0rc6", "commit": "abc"},
        {"name": "pine2ast", "version": "5.0.0rc6", "commit": None, "extra": 1},
    ],
)
def test_producer_identity_rejections(value) -> None:
    with pytest.raises(BundleAdmissionError):
        validate_producer_identity(value)


def test_producer_identity_summary() -> None:
    identity = validate_producer_identity(
        {"name": "pine2ast", "version": "5.0.0rc6", "commit": "a" * 40}
    )
    assert identity.commit_bound is True
    assert identity.to_dict()["commit_bound"] is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.clear(),
        lambda v: v.__setitem__("pine_version", True),
        lambda v: v.__setitem__("origin", "bad"),
        lambda v: v.__setitem__("annotation_span", "bad"),
        lambda v: v.__setitem__("spec_snapshot_ref", ""),
        lambda v: v.__setitem__("catalog_hash", "bad"),
        lambda v: v.__setitem__("context_hash", "bad"),
    ],
)
def test_version_context_rejections(mutate) -> None:
    value = deepcopy(load_bundle(6)["version_context"])
    mutate(value)
    with pytest.raises(BundleAdmissionError):
        validate_version_context(value)


def test_default_v1_context_rules() -> None:
    value = deepcopy(load_bundle(1)["version_context"])
    assert validate_version_context(value).pine_version == 1
    value["annotation_span"] = {}
    with pytest.raises(BundleAdmissionError):
        validate_version_context(value)
    value = deepcopy(load_bundle(6)["version_context"])
    value["annotation_span"] = None
    with pytest.raises(BundleAdmissionError):
        validate_version_context(value)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.clear(),
        lambda v: v.__setitem__("consumer", "other"),
        lambda v: v.__setitem__("minimum_consumer_version", "bad"),
        lambda v: v.__setitem__("required_capabilities", "bad"),
        lambda v: v["required_capabilities"].append(v["required_capabilities"][0]),
        lambda v: v["required_capabilities"].append("unknown"),
        lambda v: v["required_capabilities"].pop(),
    ],
)
def test_consumer_contract_rejections(mutate) -> None:
    value = deepcopy(load_bundle(6)["consumer_contract"])
    mutate(value)
    with pytest.raises(BundleAdmissionError):
        validate_consumer_contract(value, AdmissionLimits())


def test_consumer_contract_dependency_limit() -> None:
    value = deepcopy(load_bundle(6)["consumer_contract"])
    with pytest.raises(BundleAdmissionError):
        validate_consumer_contract(value, AdmissionLimits(max_dependency_count=1))


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"name": "", "encoding": "utf-8", "byte_length": 1, "source_hash": "sha256:" + "0" * 64},
        {"name": "x", "encoding": "latin1", "byte_length": 1, "source_hash": "sha256:" + "0" * 64},
        {
            "name": "x",
            "encoding": "utf-8",
            "byte_length": True,
            "source_hash": "sha256:" + "0" * 64,
        },
        {"name": "x", "encoding": "utf-8", "byte_length": 1, "source_hash": "bad"},
    ],
)
def test_source_descriptor_rejections(value) -> None:
    with pytest.raises(BundleAdmissionError):
        validate_source_descriptor(value)


def test_diagnostics_validation() -> None:
    assert validate_diagnostics([], CompilationMode.PRODUCTION) == ()
    with pytest.raises(BundleAdmissionError):
        validate_diagnostics({}, CompilationMode.PRODUCTION)
    with pytest.raises(BundleAdmissionError):
        validate_diagnostics(["bad"], CompilationMode.PRODUCTION)
    rows = [{"severity": "ERROR"}]
    with pytest.raises(BundleAdmissionError):
        validate_diagnostics(rows, CompilationMode.PRODUCTION)
    assert len(validate_diagnostics(rows, CompilationMode.ANALYSIS)) == 1


def test_mode_normalization_and_invalid_mode() -> None:
    assert Mode.normalize("analysis") is Mode.ANALYSIS
    assert Mode.normalize(Mode.PRODUCTION) is Mode.PRODUCTION
    with pytest.raises(ValueError):
        Mode.normalize("bad")


def test_fact_type_view_validation() -> None:
    assert FactTypeView.from_fact(None, path="$") is None
    view = FactTypeView.from_fact(
        {"base": "float", "qualifier": "series", "nullable": True}, path="$"
    )
    assert view and view.to_dict()["base"] == "float"
    for value in (
        "bad",
        {},
        {"base": "", "qualifier": "series", "nullable": True},
        {"base": "float", "qualifier": "bad", "nullable": True},
        {"base": "float", "qualifier": "series", "nullable": 1},
    ):
        with pytest.raises(BundleAdmissionError):
            FactTypeView.from_fact(value, path="$")


def build_facts(payload, *, production=True):
    bundle, ast = valid_parts()
    return SemanticFactsIndex.build(
        payload,
        ast_view=ast,
        version_context=bundle["version_context"],
        production=production,
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.clear(),
        lambda p: p.__setitem__("extra", 1),
        lambda p: p.__setitem__("schema_id", "bad"),
        lambda p: p.__setitem__("catalog_hash", "bad"),
        lambda p: p.__setitem__("version_context_ref", "bad"),
        lambda p: p.__setitem__("coverage", "bad"),
        lambda p: p["coverage"].__setitem__("ok", False),
        lambda p: p["coverage"].__setitem__("facts_ratio", 0.5),
        lambda p: p["coverage"].__setitem__("missing_fact_nodes", ["x"]),
        lambda p: p.__setitem__("diagnostics", "bad"),
        lambda p: p["diagnostics"].append({"severity": "ERROR"}),
        lambda p: p.__setitem__("facts", "bad"),
        lambda p: p["facts"].__setitem__(0, "bad"),
        lambda p: p["facts"][0].__setitem__("extra", 1),
        lambda p: p["facts"][0].__setitem__("node_id", ""),
        lambda p: p["facts"][1].__setitem__("node_id", p["facts"][0]["node_id"]),
        lambda p: p["facts"][0].__setitem__("node_id", "missing"),
        lambda p: p["facts"][0].__setitem__("node_kind", "Other"),
        lambda p: p["facts"][0].__setitem__("span", {}),
        lambda p: p["facts"][0].__setitem__("scope_id", "bad"),
        lambda p: p["facts"][0].__setitem__("classification", ""),
        lambda p: p["facts"][0].__setitem__("symbol_id", 1),
        lambda p: p["facts"][0].__setitem__("overload_id", 1),
        lambda p: p["facts"][0].__setitem__("call_form", 1),
        lambda p: p["facts"][0].__setitem__("receiver_type", 1),
        lambda p: p["facts"][0].__setitem__("semantic_rule_ids", [1]),
        lambda p: p["facts"][0].__setitem__("coercions", {}),
        lambda p: p["facts"][0].__setitem__("stateful_call", 1),
        lambda p: p["facts"].pop(),
        lambda p: p["calls"].__setitem__(0, "bad"),
        lambda p: p["calls"][0].__setitem__("extra", 1),
        lambda p: p["calls"][0].__setitem__("node_id", "missing"),
        lambda p: p["calls"].append(deepcopy(p["calls"][0])),
        lambda p: p["calls"][0].__setitem__("resolution_status", "UNRESOLVED"),
        lambda p: p["calls"][0].__setitem__("symbol_id", None),
        lambda p: p["calls"][0].__setitem__("overload_id", None),
        lambda p: p["calls"][0].__setitem__("callee", ""),
        lambda p: p["calls"][0].__setitem__("call_form", ""),
        lambda p: p["calls"][0].__setitem__("return_type", ""),
        lambda p: p["calls"][0].__setitem__("stateful", 1),
        lambda p: p["calls"][0].__setitem__("arguments", "bad"),
        lambda p: p["calls"][0]["arguments"][0].__setitem__("extra", 1),
        lambda p: p["calls"][0]["arguments"][0].__setitem__("argument_node_id", "missing"),
        lambda p: p["calls"][0]["arguments"][0].__setitem__("parameter_index", -1),
    ],
)
def test_semantic_fact_rejections(mutate) -> None:
    payload = deepcopy(load_bundle(6)["semantic_facts"])
    mutate(payload)
    with pytest.raises(BundleAdmissionError):
        build_facts(payload)


def test_fact_indexes_summary_and_payload() -> None:
    payload = deepcopy(load_bundle(6)["semantic_facts"])
    index = build_facts(payload)
    assert index.to_summary()["call_count"] == len(payload["calls"])
    assert index.fact_payload(next(iter(index.fact_by_node_id)))["node_id"]


def test_analysis_fact_index_can_keep_unresolved_call() -> None:
    payload = deepcopy(load_bundle(6)["semantic_facts"])
    call = payload["calls"][0]
    node_id = call["node_id"]
    call["resolution_status"] = "UNRESOLVED"
    call["symbol_id"] = None
    call["overload_id"] = None
    for fact in payload["facts"]:
        if fact["node_id"] == node_id:
            fact["symbol_id"] = None
            fact["overload_id"] = None
    index = build_facts(payload, production=False)
    assert node_id not in index.call_by_node_id


def test_validate_and_inspect_invalid_bundle_paths() -> None:
    report = None
    from ast2python import validate_consumer_bundle

    report = validate_consumer_bundle({})
    assert report.ok is False
    with pytest.raises(BundleAdmissionError):
        inspect_consumer_bundle({})


def test_ast_view_rejects_alias_fields_and_non_root_index_zero() -> None:
    bundle = load_bundle(6)
    aliased = deepcopy(bundle)
    aliased["ast"]["items"][0]["type"] = "VarDeclaration"
    with pytest.raises(BundleAdmissionError, match="A2P_AST_ALIAS_FIELD"):
        StrictASTView.build(
            aliased["ast"],
            aliased["node_index"],
            version_context=aliased["version_context"],
        )

    reordered = deepcopy(bundle)
    reordered["node_index"][0], reordered["node_index"][1] = (
        reordered["node_index"][1],
        reordered["node_index"][0],
    )
    for ordinal, row in enumerate(reordered["node_index"]):
        row["ordinal"] = ordinal
    with pytest.raises(BundleAdmissionError, match="A2P_NODE_INDEX_ROOT_ORDER"):
        StrictASTView.build(
            reordered["ast"],
            reordered["node_index"],
            version_context=reordered["version_context"],
        )


def test_mapping_input_rejects_cycles_tuples_and_preconversion_depth() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    with pytest.raises(BundleAdmissionError, match="A2P_JSON_CYCLE"):
        load_bundle_input(cyclic, AdmissionLimits())
    with pytest.raises(BundleAdmissionError, match="A2P_JSON_VALUE_TYPE"):
        load_bundle_input({"tuple": (1, 2)}, AdmissionLimits())
    nested: dict[str, object] = {"value": 1}
    for _ in range(5):
        nested = {"nested": nested}
    with pytest.raises(BundleAdmissionError, match="A2P_JSON_DEPTH"):
        load_bundle_input(nested, AdmissionLimits(max_json_depth=4))


def test_version_annotation_span_and_ast_indexes_are_immutable() -> None:
    original = load_bundle(6)
    admitted = admit_consumer_bundle(original)
    original["version_context"]["annotation_span"]["start_line"] = 999
    assert admitted.version_context.annotation_span is not None
    assert admitted.version_context.annotation_span["start_line"] == 1
    with pytest.raises(TypeError):
        admitted.version_context.annotation_span["start_line"] = 2  # type: ignore[index]
    assert admitted.ast.node_by_id is admitted.ast.nodes
    assert admitted.ast.children_by_node_id[admitted.ast.root_node_id]


def test_installed_pine2ast_version_is_exact(monkeypatch) -> None:
    import pine2ast

    monkeypatch.setattr(pine2ast, "__version__", "5.0.0rc5")
    with pytest.raises(BundleAdmissionError, match="A2P_PINE2AST_VERSION_MISMATCH"):
        admit_consumer_bundle(load_bundle(6))


def test_same_line_source_span_columns_are_ordered() -> None:
    version_context = deepcopy(load_bundle(6)["version_context"])
    version_context["annotation_span"]["start_col"] = 20
    version_context["annotation_span"]["end_col"] = 10
    with pytest.raises(BundleAdmissionError, match="A2P_SOURCE_SPAN_ORDER"):
        validate_version_context(version_context)


def test_semantic_facts_embedded_version_context_is_exact() -> None:
    bundle, ast = valid_parts()
    payload = deepcopy(bundle["semantic_facts"])
    payload["version_context"]["spec_snapshot_ref"] = "tampered"
    with pytest.raises(BundleAdmissionError, match="A2P_FACTS_VERSION_CONTEXT"):
        SemanticFactsIndex.build(
            payload,
            ast_view=ast,
            version_context=bundle["version_context"],
            production=True,
        )
