from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy

import pytest
from pine2ast.hardening.model import content_hash

from ast2python import AdmissionLimits, admit_consumer_bundle
from ast2python.errors import BundleAdmissionError
from tests.conftest import load_bundle

Mutator = Callable[[dict], object]


def reseal_bundle(bundle: dict) -> dict:
    body = {key: value for key, value in bundle.items() if key != "content_hash"}
    bundle["content_hash"] = content_hash(body)
    return bundle


def reseal_facts(bundle: dict) -> dict:
    facts = bundle["semantic_facts"]
    facts_body = {key: value for key, value in facts.items() if key != "content_hash"}
    facts["content_hash"] = content_hash(facts_body)
    bundle["artifacts"]["semantic_facts_hash"] = content_hash(facts)
    return reseal_bundle(bundle)


def reseal_node_index(bundle: dict) -> dict:
    bundle["artifacts"]["node_index_hash"] = content_hash(bundle["node_index"])
    return reseal_bundle(bundle)


def mutate_schema_id(bundle: dict) -> None:
    bundle["schema_id"] = "wrong.schema"


def mutate_schema_version(bundle: dict) -> None:
    bundle["schema_version"] = "9.9.9"


def mutate_bad_hash(bundle: dict) -> None:
    bundle["content_hash"] = "sha256:" + "0" * 64


def mutate_version_mismatch(bundle: dict) -> None:
    bundle["version_context"]["pine_version"] = 5


def mutate_catalog_hash(bundle: dict) -> None:
    bundle["version_context"]["catalog_hash"] = "sha256:" + "1" * 64


def mutate_ast_hash(bundle: dict) -> None:
    bundle["artifacts"]["ast_hash"] = "sha256:" + "2" * 64


def mutate_facts_hash(bundle: dict) -> None:
    bundle["artifacts"]["semantic_facts_hash"] = "sha256:" + "3" * 64


def mutate_node_index_hash(bundle: dict) -> None:
    bundle["artifacts"]["node_index_hash"] = "sha256:" + "4" * 64


def mutate_duplicate_node_id(bundle: dict) -> None:
    bundle["node_index"][1]["node_id"] = bundle["node_index"][0]["node_id"]
    reseal_node_index(bundle)


def mutate_missing_fact(bundle: dict) -> None:
    bundle["semantic_facts"]["facts"].pop()
    reseal_facts(bundle)


def mutate_unresolved_call(bundle: dict) -> None:
    bundle["semantic_facts"]["calls"][0]["resolution_status"] = "UNRESOLVED"
    reseal_facts(bundle)


def mutate_missing_overload(bundle: dict) -> None:
    node_id = bundle["semantic_facts"]["calls"][0]["node_id"]
    bundle["semantic_facts"]["calls"][0]["overload_id"] = None
    for fact in bundle["semantic_facts"]["facts"]:
        if fact["node_id"] == node_id:
            fact["overload_id"] = None
            break
    reseal_facts(bundle)


def mutate_blocking_diagnostic(bundle: dict) -> None:
    bundle["diagnostics"] = [{"severity": "ERROR", "code": "X", "message": "blocked", "span": {}}]
    reseal_bundle(bundle)


def mutate_unknown_capability(bundle: dict) -> None:
    bundle["consumer_contract"]["required_capabilities"].append("unknown_capability")
    reseal_bundle(bundle)


def mutate_source_hash(bundle: dict) -> None:
    bundle["source"]["source_hash"] = "sha256:" + "5" * 64


def mutate_producer(bundle: dict) -> None:
    bundle["producer"]["name"] = "other"
    reseal_bundle(bundle)


def mutate_linked_artifact(bundle: dict) -> None:
    name = next(iter(bundle["linked_artifacts"]))
    bundle["linked_artifacts"][name]["tampered"] = True


def mutate_version_type(bundle: dict) -> None:
    bundle["version_context"]["pine_version"] = True
    reseal_bundle(bundle)


def mutate_future_version(bundle: dict) -> None:
    bundle["version_context"]["pine_version"] = 7
    reseal_bundle(bundle)


def mutate_extra_property(bundle: dict) -> None:
    bundle["unexpected"] = True
    reseal_bundle(bundle)


def mutate_facts_version_context(bundle: dict) -> None:
    bundle["semantic_facts"]["version_context"]["spec_snapshot_ref"] = "tampered"
    reseal_facts(bundle)


def mutate_scope(bundle: dict) -> None:
    bundle["semantic_facts"]["facts"][0]["scope_id"] = "invalid-scope"
    reseal_facts(bundle)


def mutate_call_symbol_mismatch(bundle: dict) -> None:
    bundle["semantic_facts"]["calls"][0]["symbol_id"] = "pine:function:wrong"
    reseal_facts(bundle)


def mutate_node_kind(bundle: dict) -> None:
    bundle["node_index"][0]["kind"] = "NotProgram"
    reseal_node_index(bundle)


def mutate_node_span(bundle: dict) -> None:
    bundle["node_index"][0]["span"]["end_offset"] += 1
    reseal_node_index(bundle)


def mutate_capability_duplicate(bundle: dict) -> None:
    bundle["consumer_contract"]["required_capabilities"].append(
        bundle["consumer_contract"]["required_capabilities"][0]
    )
    reseal_bundle(bundle)


MUTATORS: list[tuple[str, Mutator]] = [
    ("wrong schema ID", mutate_schema_id),
    ("wrong schema version", mutate_schema_version),
    ("bad content hash", mutate_bad_hash),
    ("version mismatch", mutate_version_mismatch),
    ("catalog hash mismatch", mutate_catalog_hash),
    ("AST hash mismatch", mutate_ast_hash),
    ("facts hash mismatch", mutate_facts_hash),
    ("node-index hash mismatch", mutate_node_index_hash),
    ("duplicate node ID", mutate_duplicate_node_id),
    ("missing fact", mutate_missing_fact),
    ("unresolved call", mutate_unresolved_call),
    ("missing overload ID", mutate_missing_overload),
    ("blocking diagnostic", mutate_blocking_diagnostic),
    ("unknown capability", mutate_unknown_capability),
    ("source hash mismatch", mutate_source_hash),
    ("producer identity mismatch", mutate_producer),
    ("changed linked artifact", mutate_linked_artifact),
    ("wrong type in PineVersionContext", mutate_version_type),
    ("future Pine version", mutate_future_version),
    ("extra top-level property", mutate_extra_property),
    ("semantic facts version-context mismatch", mutate_facts_version_context),
    ("altered scope ID", mutate_scope),
    ("call/fact symbol mismatch", mutate_call_symbol_mismatch),
    ("node kind mismatch", mutate_node_kind),
    ("node span mismatch", mutate_node_span),
    ("duplicate capability", mutate_capability_duplicate),
]


@pytest.mark.parametrize(("name", "mutator"), MUTATORS, ids=[item[0] for item in MUTATORS])
def test_structural_mutants_are_rejected(name: str, mutator: Mutator) -> None:
    del name
    bundle = deepcopy(load_bundle(6))
    mutator(bundle)
    with pytest.raises(BundleAdmissionError):
        admit_consumer_bundle(bundle)


def test_duplicate_json_key_is_rejected() -> None:
    raw = b'{"schema_id":"a","schema_id":"b"}'
    with pytest.raises(BundleAdmissionError, match="A2P_JSON_DUPLICATE_KEY"):
        admit_consumer_bundle(raw)


def test_nan_is_rejected() -> None:
    with pytest.raises(BundleAdmissionError, match="A2P_JSON_NONFINITE"):
        admit_consumer_bundle(b'{"value":NaN}')


def test_oversized_bundle_is_rejected() -> None:
    raw = json.dumps(load_bundle(6), separators=(",", ":")).encode()
    with pytest.raises(BundleAdmissionError, match="A2P_BUNDLE_TOO_LARGE"):
        admit_consumer_bundle(raw, limits=AdmissionLimits(max_bundle_bytes=100))


def test_excessive_depth_is_rejected() -> None:
    bundle = load_bundle(6)
    bundle["linked_artifacts"]["deep"] = {"a": {"b": {"c": {"d": 1}}}}
    reseal_bundle(bundle)
    with pytest.raises(BundleAdmissionError, match="A2P_JSON_DEPTH"):
        admit_consumer_bundle(bundle, limits=AdmissionLimits(max_json_depth=4))


def test_excessive_nodes_are_rejected() -> None:
    with pytest.raises(BundleAdmissionError, match="A2P_AST_NODE_LIMIT"):
        admit_consumer_bundle(load_bundle(6), limits=AdmissionLimits(max_ast_nodes=2))
