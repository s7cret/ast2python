"""The producer's context is admitted once and sealed in generated dependencies."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pine2ast.hardening.consumer_bundle import (
    ConsumerBundleError,
    build_consumer_bundle,
    verify_consumer_bundle,
)
from pine2ast.hardening.model import content_hash
from pine2ast.libraries import LibraryStore, link_libraries

from ast2python import admit_consumer_bundle, compile_consumer_bundle
from ast2python.errors import BundleInvariantError
from ast2python.lowering import load_pinelib_target_manifest
from tests.test_locked_library_execution import advance, library, runtime_for, script


def inputs(version):
    code = script("[a,b]=lib.pair()\nplot(lib.value()+a+b)", version=version)
    return link_libraries(
        code,
        LibraryStore.create(
            {"user/Lib/1": library("export value()=>2\nexport pair()=>[3,4]", version=version)}
        ),
    )


@pytest.mark.parametrize("version", [5, 6])
def test_context_preserves_linkage_without_redundant_compile_argument(version):
    linked = inputs(version)
    bundle = build_consumer_bundle(linked.code, linked_source=linked)
    admitted = admit_consumer_bundle(bundle)
    assert admitted.schema_version == "1.1.0"
    assert admitted.library_context["linkage_receipt_hash"] == linked.receipt()["content_hash"]
    with pytest.raises(TypeError):
        admitted.library_context["exported_functions"][0]["minimum_return_qualifier"] = "const"
    one = compile_consumer_bundle(bundle, target=load_pinelib_target_manifest())
    two = compile_consumer_bundle(
        bundle, target=load_pinelib_target_manifest(), linked_source=linked
    )
    assert one.artifact.to_dict() == two.artifact.to_dict()
    # The independent arithmetic oracle is 2 + 3 + 4 on every bar.
    runtime, cls = runtime_for(one)
    assert advance(runtime, cls, [11, 17]) == [9, 9]
    checkpoint = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    restored, restored_cls = runtime_for(one)
    restored.restore(checkpoint)
    assert advance(restored, restored_cls, [23], start=2) == [9, 9, 9]
    assert advance(runtime, cls, [23], start=2) == [9, 9, 9]
    assert restored.checkpoint().to_dict() == runtime.checkpoint().to_dict()
    # Literal results must not be implemented using persistent local wrappers.
    assert "local-series:" not in one.emitted.code


@pytest.mark.parametrize("version", [5, 6])
def test_source_only_legacy_build_cannot_claim_linked_compilation(version):
    linked = inputs(version)
    legacy = build_consumer_bundle(linked.code)
    assert admit_consumer_bundle(legacy).schema_version == "1.0.0"
    with pytest.raises(BundleInvariantError, match="A2P_LIBRARY_CONTEXT"):
        compile_consumer_bundle(legacy, target=load_pinelib_target_manifest(), linked_source=linked)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "attack", ["context", "capability", "downgrade", "unknown_capability", "unknown_field"]
)
def test_compiler_context_contract_fails_closed_after_resealing(version, attack):
    linked = inputs(version)
    bundle = build_consumer_bundle(linked.code, linked_source=linked)
    if attack in {"context", "downgrade"}:
        del bundle["library_context"]
    if attack in {"capability", "downgrade"}:
        bundle["consumer_contract"]["required_capabilities"].remove("library_qualifier_context_v1")
    if attack == "downgrade":
        bundle["schema_version"] = "1.0.0"
    if attack == "unknown_capability":
        bundle["consumer_contract"]["required_capabilities"].append("library_qualifier_context_v2")
    if attack == "unknown_field":
        bundle["arbitrary_context"] = {}
    bundle["content_hash"] = content_hash({k: v for k, v in bundle.items() if k != "content_hash"})
    with pytest.raises(BundleInvariantError):
        admit_consumer_bundle(bundle)


@pytest.mark.parametrize("version", [5, 6])
def test_pre_floor_serialized_legacy_facts_admit_but_source_reverification_is_exact(version):
    # Captured from the immutable pre-floor producer, not a runtime value oracle.
    path = Path(__file__).parent / "fixtures" / "exported_floor_legacy" / f"pine-v{version}.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    original = deepcopy(fixture["bundle"])
    admitted = admit_consumer_bundle(original, expected_producer_commit="a" * 40)
    assert admitted.schema_version == "1.0.0"
    assert admitted.library_context is None
    assert original == fixture["bundle"]
    with pytest.raises(ConsumerBundleError, match="source and (AST|semantic facts) do not match"):
        verify_consumer_bundle(
            original, source=fixture["source"], expected_producer_commit="a" * 40
        )
    current = build_consumer_bundle(fixture["source"], producer_commit="a" * 40)
    plot = next(c for c in current["semantic_facts"]["calls"] if c["callee"] == "plot")
    assert plot["arguments"][0]["actual_qualifier"] == "const"
    assert current["content_hash"] != original["content_hash"]
