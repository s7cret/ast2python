from __future__ import annotations

import json

import pytest

from ast2python import (
    AdmissionLimits,
    AnalysisOnlyError,
    BundleAdmissionError,
    admit_consumer_bundle,
    inspect_consumer_bundle,
    open_compilation_session,
    validate_consumer_bundle,
)
from tests.conftest import FIXTURE_ROOT, load_bundle


def test_exact_six_consumer_bundles_are_admitted() -> None:
    for version in range(1, 7):
        admitted = admit_consumer_bundle(FIXTURE_ROOT / f"pine-v{version}-consumer-bundle.json")
        assert admitted.version_context.pine_version == version
        assert admitted.schema_id == "pine2ast.consumer_bundle.v1"
        assert admitted.schema_version == "1.0.0"
        assert admitted.runnable_output_allowed is True
        assert len(admitted.ast.nodes) == len(admitted.semantic_facts.fact_by_node_id)


def test_mapping_bytes_and_path_are_supported() -> None:
    bundle = load_bundle(6)
    payload = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
    path = FIXTURE_ROOT / "pine-v6-consumer-bundle.json"
    assert admit_consumer_bundle(bundle).content_hash == bundle["content_hash"]
    assert admit_consumer_bundle(payload).content_hash == bundle["content_hash"]
    assert admit_consumer_bundle(path).content_hash == bundle["content_hash"]


def test_plain_string_is_rejected_as_ambiguous() -> None:
    with pytest.raises(BundleAdmissionError, match="A2P_BUNDLE_STRING_AMBIGUOUS"):
        admit_consumer_bundle("{}")  # type: ignore[arg-type]


def test_raw_ast_and_wrappers_are_rejected(bundle_v6: dict) -> None:
    with pytest.raises(BundleAdmissionError):
        admit_consumer_bundle(bundle_v6["ast"])
    with pytest.raises(BundleAdmissionError):
        admit_consumer_bundle({"ast": bundle_v6})


def test_admitted_views_are_immutable() -> None:
    admitted = admit_consumer_bundle(load_bundle(6))
    with pytest.raises(TypeError):
        admitted.source["name"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        admitted.ast.nodes[admitted.ast.root_node_id] = admitted.ast.node(admitted.ast.root_node_id)  # type: ignore[index]
    first_fact = next(iter(admitted.semantic_facts.fact_by_node_id.values()))
    with pytest.raises(TypeError):
        first_fact.raw["scope_id"] = "changed"  # type: ignore[index]


def test_validate_returns_structured_report() -> None:
    report = validate_consumer_bundle(load_bundle(5))
    assert report.ok is True
    assert report.pine_version == 5
    assert report.findings == ()


def test_inspect_never_returns_runnable_output() -> None:
    summary = inspect_consumer_bundle(load_bundle(4))
    assert summary["mode"] == "ANALYSIS"
    assert summary["runnable_output_allowed"] is False
    assert summary["version_context"]["pine_version"] == 4


def test_compilation_session_has_only_admitted_version_identity() -> None:
    session = open_compilation_session(load_bundle(6))
    assert session.pine_version == 6
    assert session.version_context.catalog_hash.startswith("sha256:")
    session.require_runnable_output()
    analysis = open_compilation_session(load_bundle(6), mode="analysis")
    with pytest.raises(AnalysisOnlyError):
        analysis.require_runnable_output()


def test_limits_can_be_lowered_but_not_raised_above_absolute() -> None:
    with pytest.raises(BundleAdmissionError):
        AdmissionLimits(max_bundle_bytes=10**9)
    with pytest.raises(BundleAdmissionError):
        admit_consumer_bundle(load_bundle(6), limits=AdmissionLimits(max_ast_nodes=1))


def test_ast_nodes_are_bound_to_producer_node_index() -> None:
    admitted = admit_consumer_bundle(load_bundle(6))
    root = admitted.ast.node(admitted.ast.root_node_id)
    assert root.kind == "Program"
    assert root.child_node_ids
    assert all(node_id in admitted.ast.nodes for node_id in root.child_node_ids)


def test_semantic_fact_indexes_are_complete() -> None:
    admitted = admit_consumer_bundle(load_bundle(6))
    assert set(admitted.semantic_facts.fact_by_node_id) == set(admitted.ast.nodes)
    assert admitted.semantic_facts.call_by_node_id
    assert admitted.semantic_facts.symbol_references
    assert admitted.semantic_facts.overload_references
