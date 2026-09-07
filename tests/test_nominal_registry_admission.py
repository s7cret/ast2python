"""Admission boundary tests; registry emission and session wiring are not claimed.

Fixture modules append an independently authored registry to real compiler output
and seal it through the ordinary artifact builder. Every successful admission
first verifies the sealed module and envelope, before executing its namespace.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import MappingProxyType

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pinelib.errors import PL_REFERENCE_TYPE, PineRuntimeError
from pinelib.reference.registry import NominalTypeRegistry

from ast2python import BundleInvariantError, compile_consumer_bundle
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.artifacts.generated import (
    build_generated_artifact_v3,
    verify_generated_artifact_v3,
)
from ast2python.artifacts.nominal_registry import admitted_nominal_registry
from ast2python.lowering import load_pinelib_target_manifest

REGISTRY = "compiler.nominal_registry.v1"
NOMINAL = "compiler.nominal_types.v1"
ABSENT = object()


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def compiled():
    target = load_pinelib_target_manifest()
    results = {}
    for version in range(1, 7):
        declaration = "indicator" if version >= 5 else "study"
        source = f'//@version={version}\n{declaration}("admission")\nplot(close)\n'
        results[version] = compile_consumer_bundle(
            build_consumer_bundle(source, source_name="admission.pine", producer_commit="1" * 40),
            target=target,
            module_name=f"registry_v{version}",
            expected_pine2ast_commit="1" * 40,
            producer_commit="2" * 40,
        )
    return target, results


def payload_for(compiled, version=6, *, empty=False):
    source_hash = compiled[1][version].artifact.payload["source_hash"]
    enum = f"enum:{source_hash}:Side:enum-declaration"
    udt = f"udt:{source_hash}:Order:type-declaration"
    return {
        "schema_id": "pinelib.nominal_registry.v1",
        "pine_version": version,
        "source_hash": source_hash,
        "types": (
            []
            if empty
            else [
                {
                    "id": enum,
                    "kind": "enum",
                    "members": [
                        {"name": "buy", "title": "Long"},
                        {"name": "sell", "title": "Short"},
                    ],
                },
                {
                    "id": udt,
                    "kind": "udt",
                    "fields": [
                        {"name": "side", "type": enum, "varip": False},
                        {"name": "ticks", "type": "int", "varip": True},
                        {"name": "samples", "type": "array<float>", "varip": False},
                    ],
                },
            ]
        ),
    }


def sealed_fixture(compiled, *, version=6, payload=ABSENT, capabilities=()):
    target, results = compiled
    result = results[version]
    plan = replace(
        result.plan, required_capabilities=result.plan.required_capabilities | set(capabilities)
    )
    plan = replace(plan, content_hash=sha(canonical_json_bytes(plan.to_body_dict())))
    code = result.emitted.code
    if payload is not ABSENT:
        code += f"\nNOMINAL_TYPE_REGISTRY = {payload!r}\n"
    emitted = replace(result.emitted, code=code, code_hash=sha(code.encode("utf-8")))
    original = result.artifact.payload
    artifact = build_generated_artifact_v3(
        bundle_hash=plan.bundle_hash,
        source_hash=plan.source_hash,
        version_context=original["version_context"],
        plan=plan,
        target=target,
        emitted=emitted,
        producer_commit="2" * 40,
        ast_hash=original["ast_hash"],
        semantic_facts_hash=original["semantic_facts_hash"],
        node_index_hash=original["node_index_hash"],
    ).to_dict()
    # This future-profile fixture proves admission, not target support/emission.
    verify_generated_artifact_v3(artifact, plan=plan, target=target, emitted=emitted)
    assert sha(emitted.code.encode("utf-8")) == artifact["emitted_module_hash"]
    namespace = {}
    exec(compile(emitted.code, emitted.module_name + ".py", "exec"), namespace)
    return namespace, artifact, emitted


@pytest.mark.parametrize("version", [5, 6])
def test_sealed_registry_admits_complete_records_before_any_callback(compiled, version):
    payload = payload_for(compiled, version)
    namespace, envelope, _ = sealed_fixture(
        compiled, version=version, payload=payload, capabilities=(REGISTRY, NOMINAL)
    )
    registry = admitted_nominal_registry(
        MappingProxyType(namespace),
        MappingProxyType(envelope),
        admit_registry=NominalTypeRegistry.from_json,
    )
    assert type(registry) is NominalTypeRegistry
    assert registry.to_json() == payload
    enum, udt = payload["types"]
    assert registry.enum_member(enum["id"], "sell", 1).title == "Short"
    fields = registry.udt_schema(udt["id"]).fields
    assert [(f.name, f.type.text, f.varip) for f in fields] == [
        ("side", enum["id"], False),
        ("ticks", "int", True),
        ("samples", "array<float>", False),
    ]


@pytest.mark.parametrize("version", [5, 6])
def test_empty_current_registry_is_explicit_and_distinct_from_legacy_absence(compiled, version):
    payload = payload_for(compiled, version, empty=True)
    namespace, envelope, _ = sealed_fixture(
        compiled, version=version, payload=payload, capabilities=(REGISTRY,)
    )
    registry = admitted_nominal_registry(
        namespace, envelope, admit_registry=NominalTypeRegistry.from_json
    )
    assert type(registry) is NominalTypeRegistry
    assert registry.to_json() == payload


@pytest.mark.parametrize("version", range(1, 7))
def test_legacy_nonnominal_artifact_has_explicit_absence(compiled, version):
    namespace, envelope, _ = sealed_fixture(compiled, version=version)
    assert (
        admitted_nominal_registry(namespace, envelope, admit_registry=NominalTypeRegistry.from_json)
        is None
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("caps", [(), (NOMINAL,)])
def test_literal_without_exact_registry_capability_is_rejected(compiled, version, caps):
    namespace, envelope, _ = sealed_fixture(
        compiled, version=version, payload=payload_for(compiled, version), capabilities=caps
    )
    with pytest.raises(BundleInvariantError, match="A2P_NOMINAL_REGISTRY_CAPABILITY"):
        admitted_nominal_registry(namespace, envelope, admit_registry=NominalTypeRegistry.from_json)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "caps,code",
    [
        ((REGISTRY,), "A2P_NOMINAL_REGISTRY_MISSING"),
        ((REGISTRY, NOMINAL), "A2P_NOMINAL_REGISTRY_MISSING"),
        ((NOMINAL,), "A2P_NOMINAL_REGISTRY_CAPABILITY"),
    ],
)
def test_capabilities_never_fall_back_to_callback_learned_declarations(
    compiled, version, caps, code
):
    namespace, envelope, _ = sealed_fixture(compiled, version=version, capabilities=caps)
    with pytest.raises(BundleInvariantError, match=code):
        admitted_nominal_registry(namespace, envelope, admit_registry=NominalTypeRegistry.from_json)


@pytest.mark.parametrize("version", [5, 6])
def test_actual_prior_nominal_compiler_output_requires_recompilation(compiled, version):
    # Preserve the real pre-registry output captured before emission wiring.
    # Recompiling it here would instead test the new registry-capable producer.
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / f"nominal_registry_legacy_v{version}.json").read_text(
            encoding="utf-8"
        )
    )
    envelope = fixture["artifact"]
    verify_generated_artifact_v3(envelope)
    assert sha(fixture["module"].encode("utf-8")) == envelope["emitted_module_hash"]
    assert sha(fixture["source"].encode("utf-8")) == envelope["source_hash"]
    assert envelope["version_context"]["pine_version"] == version
    namespace = {}
    exec(compile(fixture["module"], "prior_nominal.py", "exec"), namespace)
    assert NOMINAL in envelope["required_capabilities"]
    assert "NOMINAL_TYPE_REGISTRY" not in namespace
    with pytest.raises(BundleInvariantError, match="A2P_NOMINAL_REGISTRY_CAPABILITY.*recompile"):
        admitted_nominal_registry(namespace, envelope, admit_registry=NominalTypeRegistry.from_json)


@pytest.mark.parametrize("version", range(1, 5))
@pytest.mark.parametrize(
    "caps,literal", [((REGISTRY,), True), ((REGISTRY,), False), ((), True), ((NOMINAL,), False)]
)
def test_legacy_versions_reject_registry_profile_even_with_zero_types(
    compiled, version, caps, literal
):
    namespace, envelope, _ = sealed_fixture(
        compiled,
        version=version,
        payload=payload_for(compiled, version, empty=True) if literal else ABSENT,
        capabilities=caps,
    )
    with pytest.raises(BundleInvariantError, match="A2P_NOMINAL_REGISTRY_VERSION"):
        admitted_nominal_registry(namespace, envelope, admit_registry=NominalTypeRegistry.from_json)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "field,value",
    [
        ("source_hash", "sha256:" + "f" * 64),
        ("pine_version", 4),
        ("pine_version", True),
        ("schema_id", "pinelib.nominal_registry.v2"),
    ],
)
def test_registry_identity_is_admitted_by_runtime_against_exact_envelope(
    compiled, version, field, value
):
    payload = payload_for(compiled, version)
    payload[field] = value
    namespace, envelope, _ = sealed_fixture(
        compiled, version=version, payload=payload, capabilities=(REGISTRY,)
    )
    with pytest.raises(PineRuntimeError) as error:
        admitted_nominal_registry(namespace, envelope, admit_registry=NominalTypeRegistry.from_json)
    assert error.value.code == PL_REFERENCE_TYPE


@pytest.mark.parametrize("payload", [None, {}, [], "registry"])
def test_present_malformed_literal_cannot_be_treated_as_missing_legacy_metadata(compiled, payload):
    namespace, envelope, _ = sealed_fixture(compiled, payload=payload, capabilities=(REGISTRY,))
    with pytest.raises(PineRuntimeError) as error:
        admitted_nominal_registry(namespace, envelope, admit_registry=NominalTypeRegistry.from_json)
    assert error.value.code == PL_REFERENCE_TYPE


def test_undeclared_field_type_is_rejected_by_runtime_owner(compiled):
    payload = payload_for(compiled)
    payload["types"][1]["fields"][0]["type"] = f'enum:{payload["source_hash"]}:Missing:unused'
    namespace, envelope, _ = sealed_fixture(compiled, payload=payload, capabilities=(REGISTRY,))
    with pytest.raises(PineRuntimeError, match="undeclared type"):
        admitted_nominal_registry(namespace, envelope, admit_registry=NominalTypeRegistry.from_json)


def test_registry_is_independent_of_namespace_and_returned_json_mutation(compiled):
    payload = payload_for(compiled)
    namespace, envelope, _ = sealed_fixture(compiled, payload=payload, capabilities=(REGISTRY,))
    registry = admitted_nominal_registry(
        namespace, envelope, admit_registry=NominalTypeRegistry.from_json
    )
    expected = deepcopy(payload)
    original_hash = registry.content_hash
    namespace["NOMINAL_TYPE_REGISTRY"]["types"][0]["members"][1]["name"] = "forged"
    namespace["NOMINAL_TYPE_REGISTRY"]["types"][1]["fields"][1]["varip"] = False
    exported = registry.to_json()
    exported["types"].clear()
    envelope["source_hash"] = "sha256:" + "f" * 64
    assert registry.to_json() == expected
    assert registry.content_hash == original_hash
    with pytest.raises(FrozenInstanceError):
        registry.udt_schema(expected["types"][1]["id"]).fields[1].varip = False
    with pytest.raises(PineRuntimeError, match="differs from its declaration"):
        registry.enum_member(expected["types"][0]["id"], "forged", 1)


@pytest.mark.parametrize("nominal", [False, True])
def test_even_legacy_absence_requires_a_complete_verified_envelope(compiled, nominal):
    namespace, envelope, _ = sealed_fixture(
        compiled,
        payload=payload_for(compiled) if nominal else ABSENT,
        capabilities=(REGISTRY,) if nominal else (),
    )
    del envelope["emitted_module_hash"]
    with pytest.raises(BundleInvariantError, match="A2P_ARTIFACT_FIELDS"):
        admitted_nominal_registry(namespace, envelope, admit_registry=NominalTypeRegistry.from_json)


@pytest.mark.parametrize("nominal", [False, True])
def test_stale_envelope_hash_is_rejected_before_any_registry_admission(compiled, nominal):
    namespace, envelope, _ = sealed_fixture(
        compiled,
        payload=payload_for(compiled) if nominal else ABSENT,
        capabilities=(REGISTRY,) if nominal else (),
    )
    envelope["source_hash"] = "sha256:" + "f" * 64
    with pytest.raises(BundleInvariantError, match="A2P_ARTIFACT_HASH"):
        admitted_nominal_registry(namespace, envelope, admit_registry=NominalTypeRegistry.from_json)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("required_capabilities", [REGISTRY, REGISTRY], "A2P_ARTIFACT_LIST"),
        ("required_capabilities", REGISTRY, "A2P_ARTIFACT_LIST"),
        ("source_hash", "not-a-sha", "A2P_ARTIFACT_HASH_FORMAT"),
        ("emitted_module_hash", "not-a-sha", "A2P_ARTIFACT_HASH_FORMAT"),
    ],
)
def test_rehashing_does_not_bypass_exact_envelope_rules(compiled, field, value, code):
    namespace, envelope, _ = sealed_fixture(
        compiled, payload=payload_for(compiled), capabilities=(REGISTRY,)
    )
    envelope[field] = value
    envelope["content_hash"] = sha(
        canonical_json_bytes({k: v for k, v in envelope.items() if k != "content_hash"})
    )
    with pytest.raises(BundleInvariantError, match=code):
        admitted_nominal_registry(namespace, envelope, admit_registry=NominalTypeRegistry.from_json)


def test_module_verification_precondition_rejects_registry_byte_tampering(compiled):
    _, envelope, emitted = sealed_fixture(
        compiled, payload=payload_for(compiled), capabilities=(REGISTRY,)
    )
    changed_code = emitted.code.replace("'title': 'Short'", "'title': 'Changed'")
    assert changed_code != emitted.code
    changed = replace(emitted, code=changed_code, code_hash=sha(changed_code.encode("utf-8")))
    # A caller must reject here, before exec/admitted_nominal_registry. These
    # data arguments cannot authenticate an arbitrary Python namespace.
    with pytest.raises(BundleInvariantError, match="A2P_ARTIFACT_MODULE"):
        verify_generated_artifact_v3(envelope, emitted=changed)
