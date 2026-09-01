from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from ast2python.admission.canonical import canonical_json_bytes
from ast2python.emission import EmittedPythonModule
from ast2python.errors import BundleInvariantError
from ast2python.lowering import LoweringDispositionStatus, LoweringPlan, TargetManifest
from ast2python.version import __version__


@dataclass(frozen=True, slots=True)
class GeneratedArtifactV3:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


def _sha256_identity(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def build_generated_artifact_v3(
    *,
    bundle_hash: str,
    source_hash: str,
    version_context: Mapping[str, Any],
    plan: LoweringPlan,
    target: TargetManifest,
    emitted: EmittedPythonModule,
    producer_commit: str | None = None,
    ast_hash: str,
    semantic_facts_hash: str,
    node_index_hash: str,
    stack_manifest_hash: str | None = None,
    producer_wheel_hash: str | None = None,
) -> GeneratedArtifactV3:
    if (
        producer_commit is None
        or len(producer_commit) != 40
        or any(char not in "0123456789abcdef" for char in producer_commit)
    ):
        raise BundleInvariantError(
            "A2P_ARTIFACT_COMMIT",
            "producer_commit must be an exact 40-character lowercase Git SHA",
        )
    disposition_counts = {
        status.value: sum(disposition.status is status for disposition in plan.dispositions)
        for status in LoweringDispositionStatus
    }
    mapped_ir_ids = {entry.ir_id for entry in emitted.source_map.entries if entry.ir_id is not None}
    import_manifest = list(emitted.import_manifest)
    build_manifest_hash = _sha256_identity(
        {
            "producer_commit": producer_commit,
            "bundle_hash": bundle_hash,
            "target_manifest_hash": target.content_hash,
            "lowering_plan_hash": plan.content_hash,
            "emitted_module_hash": emitted.code_hash,
        }
    )
    resolved_wheel_hash = producer_wheel_hash or _sha256_identity(
        {
            "name": "ast2python",
            "version": __version__,
            "commit": producer_commit,
        }
    )
    resolved_stack_hash = stack_manifest_hash or build_manifest_hash
    body: dict[str, Any] = {
        "schema_id": "openpine.generated_artifact.v3",
        "schema_version": "3.0.0",
        "producer": {
            "name": "ast2python",
            "version": __version__,
            "commit": producer_commit,
            "source_state": "COMMIT_PINNED",
        },
        "build_identity": {
            "build_manifest_hash": build_manifest_hash,
            "producer_wheel_hash": resolved_wheel_hash,
            "stack_manifest_hash": resolved_stack_hash,
        },
        "bundle_hash": bundle_hash,
        "source_hash": source_hash,
        "version_context": dict(version_context),
        "catalog_hash": plan.catalog_hash,
        "ast_hash": ast_hash,
        "semantic_facts_hash": semantic_facts_hash,
        "node_index_hash": node_index_hash,
        "lowering_pack_id": "ast2python.lowering.rc6.v1",
        "lowering_pack_hash": plan.content_hash,
        "lowering_plan_hash": plan.content_hash,
        "target_manifest_hash": target.content_hash,
        "target_abi_id": "pinelib.generated_abi.v1",
        "target_abi_hash": target.content_hash,
        "emitted_module_hash": emitted.code_hash,
        "source_map_hash": emitted.source_map.content_hash,
        "import_manifest": import_manifest,
        "import_manifest_hash": _sha256_identity({"import_manifest": import_manifest}),
        "entrypoint": {"module": emitted.module_name, "class": emitted.entrypoint_class},
        "required_operations": sorted(plan.required_operations),
        "required_capabilities": sorted(plan.required_capabilities),
        "visual_projection_policy": "VISUAL_TAPE_REQUIRED",
        "external_library_dependency_hashes": {},
        "build_determinism_identity": build_manifest_hash,
        "projection_proof": {
            "disposition_counts": disposition_counts,
            "source_node_count": len(plan.dispositions),
            "ir_node_count": len(plan.nodes),
            "source_map_entry_count": len(emitted.source_map.entries),
            "mapped_ir_count": len(mapped_ir_ids),
            "mapped_ir_coverage": mapped_ir_ids == set(plan.nodes),
        },
        "release_acceptance": {
            "pine2ast_rc6": "EXACT_CORRECTED_BUNDLE_ACCEPTED",
            "pinelib_rc6": target.release_acceptance,
            "tradingview_oracle": "NOT_CLAIMED",
        },
    }
    body["content_hash"] = _sha256_identity(body)
    return GeneratedArtifactV3(payload=body)


def verify_generated_artifact_v3(
    artifact: Mapping[str, Any],
    *,
    plan: LoweringPlan | None = None,
    target: TargetManifest | None = None,
    emitted: EmittedPythonModule | None = None,
) -> None:
    import re

    hash_re = re.compile(r"^sha256:[0-9a-f]{64}$")
    identifier_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    required = {
        "schema_id",
        "schema_version",
        "producer",
        "build_identity",
        "bundle_hash",
        "source_hash",
        "version_context",
        "catalog_hash",
        "ast_hash",
        "semantic_facts_hash",
        "node_index_hash",
        "lowering_pack_id",
        "lowering_pack_hash",
        "lowering_plan_hash",
        "target_manifest_hash",
        "target_abi_id",
        "target_abi_hash",
        "emitted_module_hash",
        "source_map_hash",
        "entrypoint",
        "required_operations",
        "required_capabilities",
        "import_manifest",
        "import_manifest_hash",
        "visual_projection_policy",
        "external_library_dependency_hashes",
        "build_determinism_identity",
        "projection_proof",
        "release_acceptance",
        "content_hash",
    }
    if set(artifact) != required:
        raise BundleInvariantError("A2P_ARTIFACT_FIELDS", "generated artifact fields are not exact")
    if (
        artifact["schema_id"] != "openpine.generated_artifact.v3"
        or artifact["schema_version"] != "3.0.0"
    ):
        raise BundleInvariantError("A2P_ARTIFACT_SCHEMA", "unsupported generated artifact schema")
    stored = artifact["content_hash"]
    body = {key: artifact[key] for key in artifact if key != "content_hash"}
    expected = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    if stored != expected:
        raise BundleInvariantError("A2P_ARTIFACT_HASH", "generated artifact content hash mismatch")
    for field in (
        "bundle_hash",
        "source_hash",
        "catalog_hash",
        "ast_hash",
        "semantic_facts_hash",
        "node_index_hash",
        "lowering_pack_hash",
        "lowering_plan_hash",
        "target_manifest_hash",
        "target_abi_hash",
        "emitted_module_hash",
        "source_map_hash",
        "import_manifest_hash",
        "build_determinism_identity",
        "content_hash",
    ):
        if (
            not isinstance(artifact.get(field), str)
            or hash_re.fullmatch(str(artifact.get(field))) is None
        ):
            raise BundleInvariantError(
                "A2P_ARTIFACT_HASH_FORMAT", f"{field} must be a sha256 identity"
            )
    producer = artifact.get("producer")
    if not isinstance(producer, Mapping) or set(producer) != {
        "name",
        "version",
        "commit",
        "source_state",
    }:
        raise BundleInvariantError("A2P_ARTIFACT_PRODUCER", "producer fields are not exact")
    if producer.get("name") != "ast2python" or producer.get("version") != __version__:
        raise BundleInvariantError("A2P_ARTIFACT_PRODUCER", "producer identity mismatch")
    commit = producer.get("commit")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise BundleInvariantError("A2P_ARTIFACT_COMMIT", "producer commit is malformed")
    if producer.get("source_state") != "COMMIT_PINNED":
        raise BundleInvariantError(
            "A2P_ARTIFACT_SOURCE_STATE", "canonical generated artifacts must be COMMIT_PINNED"
        )
    build_identity = artifact.get("build_identity")
    if not isinstance(build_identity, Mapping) or set(build_identity) != {
        "build_manifest_hash",
        "producer_wheel_hash",
        "stack_manifest_hash",
    }:
        raise BundleInvariantError(
            "A2P_ARTIFACT_BUILD_IDENTITY", "build_identity fields are not exact"
        )
    for field in (
        "build_manifest_hash",
        "producer_wheel_hash",
        "stack_manifest_hash",
    ):
        if (
            not isinstance(build_identity.get(field), str)
            or hash_re.fullmatch(str(build_identity.get(field))) is None
        ):
            raise BundleInvariantError(
                "A2P_ARTIFACT_HASH_FORMAT", f"build_identity.{field} must be a sha256 identity"
            )
    if artifact.get("lowering_pack_id") != "ast2python.lowering.rc6.v1":
        raise BundleInvariantError("A2P_ARTIFACT_LOWERING_PACK", "lowering_pack_id is invalid")
    if artifact.get("target_abi_id") != "pinelib.generated_abi.v1":
        raise BundleInvariantError("A2P_ARTIFACT_TARGET_ABI", "target_abi_id is invalid")
    if artifact.get("visual_projection_policy") != "VISUAL_TAPE_REQUIRED":
        raise BundleInvariantError(
            "A2P_ARTIFACT_VISUAL_POLICY", "visual_projection_policy must be VISUAL_TAPE_REQUIRED"
        )
    if artifact.get("external_library_dependency_hashes") != {}:
        raise BundleInvariantError(
            "A2P_ARTIFACT_EXTERNAL_LIBS",
            "external_library_dependency_hashes must be empty for the exact target",
        )
    if artifact.get("build_determinism_identity") != build_identity.get("build_manifest_hash"):
        raise BundleInvariantError(
            "A2P_ARTIFACT_BUILD_IDENTITY",
            "build_determinism_identity must match build_manifest_hash",
        )
    expected_build_manifest_hash = _sha256_identity(
        {
            "producer_commit": commit,
            "bundle_hash": artifact["bundle_hash"],
            "target_manifest_hash": artifact["target_manifest_hash"],
            "lowering_plan_hash": artifact["lowering_plan_hash"],
            "emitted_module_hash": artifact["emitted_module_hash"],
        }
    )
    if build_identity.get("build_manifest_hash") != expected_build_manifest_hash:
        raise BundleInvariantError(
            "A2P_ARTIFACT_BUILD_IDENTITY", "build_manifest_hash does not match sealed inputs"
        )
    if build_identity.get("stack_manifest_hash") != expected_build_manifest_hash:
        raise BundleInvariantError(
            "A2P_ARTIFACT_BUILD_IDENTITY",
            "stack_manifest_hash must match the sealed build manifest",
        )
    version_context = artifact.get("version_context")
    if not isinstance(version_context, Mapping):
        raise BundleInvariantError("A2P_ARTIFACT_VERSION", "version_context must be an object")
    if type(version_context.get("pine_version")) is not int or version_context.get(
        "pine_version"
    ) not in range(1, 7):
        raise BundleInvariantError("A2P_ARTIFACT_VERSION", "Pine version must be 1..6")
    if version_context.get("catalog_hash") != artifact.get("catalog_hash"):
        raise BundleInvariantError(
            "A2P_ARTIFACT_CATALOG", "artifact catalog hash differs from version context"
        )
    entrypoint = artifact.get("entrypoint")
    if not isinstance(entrypoint, Mapping) or set(entrypoint) != {"module", "class"}:
        raise BundleInvariantError("A2P_ARTIFACT_ENTRYPOINT", "entrypoint fields are not exact")
    if (
        not isinstance(entrypoint.get("module"), str)
        or identifier_re.fullmatch(entrypoint["module"]) is None
    ):
        raise BundleInvariantError("A2P_ARTIFACT_ENTRYPOINT", "entrypoint module is invalid")
    if entrypoint.get("class") != "GeneratedScript":
        raise BundleInvariantError(
            "A2P_ARTIFACT_ENTRYPOINT", "entrypoint class must be GeneratedScript"
        )
    operations = artifact.get("required_operations")
    capabilities = artifact.get("required_capabilities")
    imports = artifact.get("import_manifest")
    for label, values in (
        ("required_operations", operations),
        ("required_capabilities", capabilities),
        ("import_manifest", imports),
    ):
        if not isinstance(values, list) or not all(
            isinstance(item, str) and item for item in values
        ):
            raise BundleInvariantError("A2P_ARTIFACT_LIST", f"{label} must contain strings")
        if values != sorted(set(values)):
            raise BundleInvariantError("A2P_ARTIFACT_LIST", f"{label} must be sorted and unique")
    assert isinstance(imports, list)
    if any(item.split(".", 1)[0] in {"ast2python", "pine2ast"} for item in imports):
        raise BundleInvariantError(
            "A2P_ARTIFACT_IMPORT", "generated artifact imports compiler packages"
        )
    projection = artifact.get("projection_proof")
    projection_fields = {
        "disposition_counts",
        "source_node_count",
        "ir_node_count",
        "source_map_entry_count",
        "mapped_ir_count",
        "mapped_ir_coverage",
    }
    if not isinstance(projection, Mapping) or set(projection) != projection_fields:
        raise BundleInvariantError(
            "A2P_ARTIFACT_PROJECTION", "projection proof fields are not exact"
        )
    disposition_counts = projection.get("disposition_counts")
    status_names = {status.value for status in LoweringDispositionStatus}
    if not isinstance(disposition_counts, Mapping) or set(disposition_counts) != status_names:
        raise BundleInvariantError(
            "A2P_ARTIFACT_PROJECTION", "disposition count fields are not exact"
        )
    if not all(type(value) is int and value >= 0 for value in disposition_counts.values()):
        raise BundleInvariantError(
            "A2P_ARTIFACT_PROJECTION", "disposition counts must be nonnegative integers"
        )
    counts = [
        projection.get(key)
        for key in (
            "source_node_count",
            "ir_node_count",
            "source_map_entry_count",
            "mapped_ir_count",
        )
    ]
    if not all(type(value) is int and value >= 0 for value in counts):
        raise BundleInvariantError(
            "A2P_ARTIFACT_PROJECTION", "projection counts must be nonnegative integers"
        )
    source_node_count, ir_node_count, source_map_entry_count, mapped_ir_count = cast(
        list[int], counts
    )
    if (
        sum(disposition_counts.values()) != source_node_count
        or disposition_counts.get(LoweringDispositionStatus.REJECTED.value) != 0
        or projection.get("mapped_ir_coverage") is not True
        or source_map_entry_count < mapped_ir_count
        or ir_node_count != mapped_ir_count
    ):
        raise BundleInvariantError("A2P_ARTIFACT_PROJECTION", "projection coverage is incomplete")
    release = artifact.get("release_acceptance")
    if not isinstance(release, Mapping) or set(release) != {
        "pine2ast_rc6",
        "pinelib_rc6",
        "tradingview_oracle",
    }:
        raise BundleInvariantError(
            "A2P_ARTIFACT_RELEASE", "release acceptance fields are not exact"
        )
    if (
        release.get("pine2ast_rc6") != "EXACT_CORRECTED_BUNDLE_ACCEPTED"
        or release.get("tradingview_oracle") != "NOT_CLAIMED"
    ):
        raise BundleInvariantError(
            "A2P_ARTIFACT_RELEASE", "release acceptance statements are invalid"
        )
    if plan is not None:
        if artifact["lowering_plan_hash"] != plan.content_hash:
            raise BundleInvariantError("A2P_ARTIFACT_PLAN", "artifact plan hash mismatch")
        if operations != sorted(plan.required_operations):
            raise BundleInvariantError(
                "A2P_ARTIFACT_OPERATION", "artifact operations differ from plan"
            )
        if capabilities != sorted(plan.required_capabilities):
            raise BundleInvariantError(
                "A2P_ARTIFACT_CAPABILITY", "artifact capabilities differ from plan"
            )
        if (
            artifact["bundle_hash"] != plan.bundle_hash
            or artifact["source_hash"] != plan.source_hash
            or artifact["catalog_hash"] != plan.catalog_hash
            or version_context.get("pine_version") != plan.pine_version
            or version_context.get("context_hash") != plan.version_context_hash
            or version_context.get("catalog_hash") != plan.catalog_hash
        ):
            raise BundleInvariantError("A2P_ARTIFACT_LINEAGE", "artifact lineage differs from plan")
        expected_disposition_counts = {
            status.value: sum(disposition.status is status for disposition in plan.dispositions)
            for status in LoweringDispositionStatus
        }
        if (
            dict(disposition_counts) != expected_disposition_counts
            or projection.get("source_node_count") != len(plan.dispositions)
            or projection.get("ir_node_count") != len(plan.nodes)
            or projection.get("mapped_ir_count") != len(plan.nodes)
        ):
            raise BundleInvariantError(
                "A2P_ARTIFACT_PROJECTION", "projection counts differ from plan"
            )
    if target is not None:
        if artifact["target_manifest_hash"] != target.content_hash:
            raise BundleInvariantError("A2P_ARTIFACT_TARGET", "artifact target hash mismatch")
        if release.get("pinelib_rc6") != target.release_acceptance:
            raise BundleInvariantError("A2P_ARTIFACT_RELEASE", "target release acceptance mismatch")
    if emitted is not None:
        if artifact["emitted_module_hash"] != emitted.code_hash:
            raise BundleInvariantError("A2P_ARTIFACT_MODULE", "artifact module hash mismatch")
        if artifact["source_map_hash"] != emitted.source_map.content_hash:
            raise BundleInvariantError(
                "A2P_ARTIFACT_SOURCE_MAP", "artifact source map hash mismatch"
            )
        if imports != list(emitted.import_manifest):
            raise BundleInvariantError(
                "A2P_ARTIFACT_IMPORT", "artifact import manifest differs from emitted module"
            )
        if entrypoint != {"module": emitted.module_name, "class": emitted.entrypoint_class}:
            raise BundleInvariantError(
                "A2P_ARTIFACT_ENTRYPOINT", "artifact entrypoint differs from emitted module"
            )
        mapped_ir_ids = {
            entry.ir_id for entry in emitted.source_map.entries if entry.ir_id is not None
        }
        if (
            projection.get("source_map_entry_count") != len(emitted.source_map.entries)
            or projection.get("mapped_ir_count") != len(mapped_ir_ids)
            or (plan is not None and mapped_ir_ids != set(plan.nodes))
        ):
            raise BundleInvariantError(
                "A2P_ARTIFACT_PROJECTION",
                "projection source-map coverage differs from emitted module",
            )
