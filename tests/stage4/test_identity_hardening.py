from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import pytest

from ast2python import compile_reference_consumer_bundle as compile_consumer_bundle
from ast2python import verify_generated_artifact_v3
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.errors import BundleInvariantError
from ast2python.lowering import TargetManifest, load_reference_target_manifest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "consumer"


def _reference_payload() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            files("ast2python.target_data")
            .joinpath("reference_target_v1.json")
            .read_text(encoding="utf-8")
        ),
    )


def _reseal(payload: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    payload["content_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    return payload


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("target_name", 1),
        ("target_version", ["1.0.0"]),
        ("release_acceptance", {"status": "pending"}),
    ],
)
def test_target_manifest_rejects_non_string_identity_fields(
    field: str, replacement: object
) -> None:
    payload = _reference_payload()
    payload[field] = replacement

    with pytest.raises(BundleInvariantError):
        TargetManifest.from_mapping(_reseal(payload))


@pytest.mark.parametrize("field", ["capabilities", "allowed_imports"])
def test_target_manifest_requires_sorted_unique_string_lists(field: str) -> None:
    unsorted_payload = _reference_payload()
    unsorted_payload[field] = list(reversed(unsorted_payload[field]))
    with pytest.raises(BundleInvariantError):
        TargetManifest.from_mapping(_reseal(unsorted_payload))

    duplicate_payload = _reference_payload()
    duplicate_payload[field] = [*duplicate_payload[field], duplicate_payload[field][0]]
    with pytest.raises(BundleInvariantError):
        TargetManifest.from_mapping(_reseal(duplicate_payload))


def test_target_manifest_requires_operations_sorted_by_name() -> None:
    payload = _reference_payload()
    payload["operations"][0], payload["operations"][1] = (
        payload["operations"][1],
        payload["operations"][0],
    )

    with pytest.raises(BundleInvariantError):
        TargetManifest.from_mapping(_reseal(payload))


@pytest.mark.parametrize(
    "release_acceptance",
    ["EXACT_PINELIB_RC6_ACCEPTED", "UNPROVEN_ALTERNATIVE_ACCEPTANCE"],
)
def test_target_manifest_v1_only_accepts_reference_pending_status(
    release_acceptance: str,
) -> None:
    payload = _reference_payload()
    payload["release_acceptance"] = release_acceptance

    with pytest.raises(BundleInvariantError):
        TargetManifest.from_mapping(_reseal(payload))


def test_target_manifest_hash_is_of_materialized_body() -> None:
    manifest = load_reference_target_manifest()
    expected = "sha256:" + hashlib.sha256(canonical_json_bytes(manifest.to_body_dict())).hexdigest()

    assert manifest.content_hash == expected
    assert manifest.to_dict()["content_hash"] == expected


def _assert_target_error(code: str, mutate: Any) -> None:
    payload = _reference_payload()
    mutate(payload)
    with pytest.raises(BundleInvariantError, match=code):
        TargetManifest.from_mapping(_reseal(payload))


@pytest.mark.parametrize(
    ("code", "mutate"),
    [
        (
            "A2P_TARGET_PYTHON_NAME",
            lambda payload: payload["operations"][0].__setitem__("python_name", "bad-name"),
        ),
        (
            "A2P_TARGET_CALL_BINDING",
            lambda payload: payload["call_bindings"][0].__setitem__("extra", True),
        ),
        (
            "A2P_TARGET_PYTHON_NAME",
            lambda payload: payload["call_bindings"][0].__setitem__("python_name", "class"),
        ),
        (
            "A2P_TARGET_CALL_PARAMETERS",
            lambda payload: payload["call_bindings"][0].__setitem__("parameters", ["x", "x"]),
        ),
        (
            "A2P_TARGET_CALL_VERSIONS",
            lambda payload: payload["call_bindings"][0].__setitem__("supported_pine_versions", [7]),
        ),
        (
            "A2P_TARGET_CALL_BINDING",
            lambda payload: payload["call_bindings"].append(deepcopy(payload["call_bindings"][0])),
        ),
        (
            "A2P_TARGET_CALL_BINDING",
            lambda payload: payload["call_bindings"].reverse(),
        ),
        (
            "A2P_TARGET_VALUE_BINDING",
            lambda payload: payload["value_bindings"][0].__setitem__("python_name", "bad-name"),
        ),
        (
            "A2P_TARGET_VALUE_BINDING",
            lambda payload: payload["value_bindings"].append(
                deepcopy(payload["value_bindings"][0])
            ),
        ),
        (
            "A2P_TARGET_VALUE_BINDING",
            lambda payload: payload["value_bindings"].reverse(),
        ),
    ],
)
def test_target_manifest_deep_binding_validation(code: str, mutate: Any) -> None:
    _assert_target_error(code, mutate)


def test_lowering_plan_binds_source_hash_in_serialized_identity() -> None:
    bundle_path = FIXTURES / "pine-v6-consumer-bundle.json"
    source_hash = json.loads(bundle_path.read_text(encoding="utf-8"))["source"]["source_hash"]
    plan = compile_consumer_bundle(bundle_path).plan

    assert plan.source_hash == source_hash
    assert plan.to_body_dict()["source_hash"] == source_hash
    assert plan.to_dict()["source_hash"] == source_hash


@pytest.mark.parametrize(
    "mismatch",
    ["source_hash", "pine_version", "version_context_hash", "catalog_hash"],
)
def test_resealed_artifact_cannot_disagree_with_plan(mismatch: str) -> None:
    result = compile_consumer_bundle(FIXTURES / "pine-v6-consumer-bundle.json")
    artifact = deepcopy(result.artifact.to_dict())
    if mismatch == "source_hash":
        artifact["source_hash"] = "sha256:" + "a" * 64
    elif mismatch == "pine_version":
        artifact["version_context"]["pine_version"] = 5
    elif mismatch == "version_context_hash":
        artifact["version_context"]["context_hash"] = "sha256:" + "b" * 64
    else:
        artifact["catalog_hash"] = "sha256:" + "c" * 64
        artifact["version_context"]["catalog_hash"] = artifact["catalog_hash"]
    _reseal(artifact)

    with pytest.raises(BundleInvariantError):
        verify_generated_artifact_v3(artifact, plan=result.plan)
