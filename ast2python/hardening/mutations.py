from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ast2python.admission.bundle import BundleAdmissionService
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.artifacts import verify_generated_artifact_v3
from ast2python.emission import EmittedPythonModule
from ast2python.errors import BundleAdmissionError, BundleInvariantError
from ast2python.lowering import LoweringPlan, TargetManifest
from ast2python.lowering.validate import verify_lowering_plan_payload


@dataclass(frozen=True, slots=True)
class MutationResult:
    category: str
    mutation_id: str
    killed: bool
    error_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "mutation_id": self.mutation_id,
            "killed": self.killed,
            "error_code": self.error_code,
        }


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(payload)
    payload.pop("content_hash", None)
    payload["content_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return payload


def _bad_hash(seed: int) -> str:
    return "sha256:" + f"{seed:064x}"[-64:]


def bundle_mutants(bundle: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    base = copy.deepcopy(dict(bundle))
    mutators: list[tuple[str, Callable[[dict[str, Any]], None], bool]] = []

    def add(name: str, fn: Callable[[dict[str, Any]], None], reseal: bool = True) -> None:
        mutators.append((name, fn, reseal))

    add("schema-id", lambda d: d.__setitem__("schema_id", "wrong.bundle"))
    add("schema-version", lambda d: d.__setitem__("schema_version", "9.0.0"))
    add("producer-name", lambda d: d["producer"].__setitem__("name", "other"))
    add("producer-version", lambda d: d["producer"].__setitem__("version", "0"))
    add("producer-commit", lambda d: d["producer"].__setitem__("commit", "not-a-sha"))
    add("source-encoding", lambda d: d["source"].__setitem__("encoding", "latin-1"))
    add("source-length-negative", lambda d: d["source"].__setitem__("byte_length", -1))
    add("source-length-string", lambda d: d["source"].__setitem__("byte_length", "1"))
    add("source-hash", lambda d: d["source"].__setitem__("source_hash", "bad"))
    add("version-zero", lambda d: d["version_context"].__setitem__("pine_version", 0))
    add("version-future", lambda d: d["version_context"].__setitem__("pine_version", 7))
    add("version-string", lambda d: d["version_context"].__setitem__("pine_version", "6"))
    add("catalog-hash", lambda d: d["version_context"].__setitem__("catalog_hash", _bad_hash(1)))
    add("context-hash", lambda d: d["version_context"].__setitem__("context_hash", _bad_hash(2)))
    add("version-origin", lambda d: d["version_context"].__setitem__("origin", "guessed"))
    add("version-spec", lambda d: d["version_context"].__setitem__("spec_snapshot_ref", ""))
    add("ast-kind", lambda d: d["ast"].__setitem__("kind", "Wrapper"))
    add("ast-language", lambda d: d["ast"].__setitem__("language", "python"))
    add("ast-schema", lambda d: d["ast"].__setitem__("schema_version", "1.0"))
    add(
        "ast-version-context", lambda d: d["ast"]["version_context"].__setitem__("pine_version", 99)
    )
    add("node-index-missing", lambda d: d.pop("node_index"))
    add(
        "node-index-duplicate-id",
        lambda d: d["node_index"][1].__setitem__("node_id", d["node_index"][0]["node_id"]),
    )
    add("node-index-ordinal", lambda d: d["node_index"][1].__setitem__("ordinal", 99))
    add("node-index-kind", lambda d: d["node_index"][0].__setitem__("kind", "Other"))
    add("facts-schema", lambda d: d["semantic_facts"].__setitem__("schema_id", "wrong.facts"))
    add("facts-version", lambda d: d["semantic_facts"].__setitem__("schema_version", "0"))
    add("facts-catalog", lambda d: d["semantic_facts"].__setitem__("catalog_hash", _bad_hash(3)))
    add(
        "facts-context-ref",
        lambda d: d["semantic_facts"].__setitem__("version_context_ref", _bad_hash(4)),
    )
    add("facts-coverage", lambda d: d["semantic_facts"]["coverage"].__setitem__("ok", False))
    add("facts-missing", lambda d: d["semantic_facts"]["facts"].pop())
    add(
        "facts-duplicate",
        lambda d: d["semantic_facts"]["facts"].append(
            copy.deepcopy(d["semantic_facts"]["facts"][0])
        ),
    )
    add(
        "call-unresolved",
        lambda d: d["semantic_facts"]["calls"][0].__setitem__("resolution_status", "UNRESOLVED"),
    )
    add(
        "call-symbol-null", lambda d: d["semantic_facts"]["calls"][0].__setitem__("symbol_id", None)
    )
    add(
        "call-overload-null",
        lambda d: d["semantic_facts"]["calls"][0].__setitem__("overload_id", None),
    )
    add(
        "diagnostic-blocking", lambda d: d["diagnostics"].append({"severity": "ERROR", "code": "X"})
    )
    add("consumer-name", lambda d: d["consumer_contract"].__setitem__("consumer", "other"))
    add(
        "consumer-version",
        lambda d: d["consumer_contract"].__setitem__("minimum_consumer_version", "9"),
    )
    add(
        "capability-unknown",
        lambda d: d["consumer_contract"]["required_capabilities"].append("unknown"),
    )
    add("capability-missing", lambda d: d["consumer_contract"]["required_capabilities"].pop())
    add(
        "capability-duplicate",
        lambda d: d["consumer_contract"]["required_capabilities"].append(
            d["consumer_contract"]["required_capabilities"][0]
        ),
    )
    add("artifact-ast-hash", lambda d: d["artifacts"].__setitem__("ast_hash", _bad_hash(5)))
    add(
        "artifact-facts-hash",
        lambda d: d["artifacts"].__setitem__("semantic_facts_hash", _bad_hash(6)),
    )
    add(
        "artifact-index-hash", lambda d: d["artifacts"].__setitem__("node_index_hash", _bad_hash(7))
    )
    add("content-hash", lambda d: d.__setitem__("content_hash", _bad_hash(8)), reseal=False)

    mutants: list[tuple[str, dict[str, Any]]] = []
    for name, mutate, reseal in mutators:
        candidate = copy.deepcopy(base)
        mutate(candidate)
        mutants.append((name, _seal(candidate) if reseal else candidate))
    return mutants


def _reseal_plan(value: dict[str, Any]) -> dict[str, Any]:
    return _seal(value)


def plan_mutants(plan: LoweringPlan) -> list[tuple[str, dict[str, Any]]]:
    base = plan.to_dict()
    mutants: list[tuple[str, dict[str, Any]]] = []

    def add(name: str, mutate: Callable[[dict[str, Any]], None], reseal: bool = True) -> None:
        candidate = copy.deepcopy(base)
        mutate(candidate)
        mutants.append((name, _reseal_plan(candidate) if reseal else candidate))

    add("schema-id", lambda d: d.__setitem__("schema_id", "wrong"))
    add("schema-version", lambda d: d.__setitem__("schema_version", "2"))
    add("bundle-hash", lambda d: d.__setitem__("bundle_hash", "bad"))
    add("catalog-hash", lambda d: d.__setitem__("catalog_hash", "bad"))
    add("context-hash", lambda d: d.__setitem__("version_context_hash", "bad"))
    add("target-hash", lambda d: d.__setitem__("target_manifest_hash", _bad_hash(11)))
    add("version-zero", lambda d: d.__setitem__("pine_version", 0))
    add("version-seven", lambda d: d.__setitem__("pine_version", 7))
    add("version-string", lambda d: d.__setitem__("pine_version", "6"))
    add("root-missing", lambda d: d.__setitem__("root_ir_id", "ir:missing"))
    add("ordered-duplicate", lambda d: d["ordered_ir_ids"].__setitem__(1, d["ordered_ir_ids"][0]))
    add("ordered-remove", lambda d: d["ordered_ir_ids"].pop())
    add("ordered-reverse", lambda d: d["ordered_ir_ids"].reverse())
    add("node-id-duplicate", lambda d: d["nodes"][1].__setitem__("ir_id", d["nodes"][0]["ir_id"]))
    add("node-id-empty", lambda d: d["nodes"][0].__setitem__("ir_id", ""))
    add("node-field-remove", lambda d: d["nodes"][0].pop("effect"))
    add("node-field-extra", lambda d: d["nodes"][0].__setitem__("extra", 1))
    add("source-field-remove", lambda d: d["nodes"][0]["source"].pop("span"))
    add(
        "source-id-duplicate",
        lambda d: d["nodes"][1]["source"].__setitem__(
            "node_id", d["nodes"][0]["source"]["node_id"]
        ),
    )
    add("source-id-empty", lambda d: d["nodes"][0]["source"].__setitem__("node_id", ""))
    add("disposition-remove", lambda d: d["dispositions"].pop())
    add(
        "disposition-source-duplicate",
        lambda d: d["dispositions"][1].__setitem__(
            "source_node_id", d["dispositions"][0]["source_node_id"]
        ),
    )
    add(
        "disposition-ir-duplicate",
        lambda d: d["dispositions"][1]["ir_ids"].append(d["dispositions"][0]["ir_ids"][0]),
    )
    add("disposition-rejected", lambda d: d["dispositions"][0].__setitem__("status", "REJECTED"))
    add("opcode-unknown", lambda d: d["nodes"][0].__setitem__("opcode", "unknown"))
    add(
        "evaluation-wrong",
        lambda d: d["nodes"][0].__setitem__(
            "evaluation", "lazy" if d["nodes"][0]["evaluation"] != "lazy" else "eager"
        ),
    )
    add(
        "effect-wrong",
        lambda d: d["nodes"][0].__setitem__(
            "effect", "pure" if d["nodes"][0]["effect"] != "pure" else "state"
        ),
    )
    add("child-missing", lambda d: d["nodes"][0]["child_ir_ids"].append("ir:missing"))
    add("children-type", lambda d: d["nodes"][0].__setitem__("child_ir_ids", "bad"))
    add("rules-type", lambda d: d["nodes"][0].__setitem__("semantic_rule_ids", [1]))
    add("attributes-type", lambda d: d["nodes"][0].__setitem__("attributes", []))
    add("result-type-fields", lambda d: d["nodes"][0].__setitem__("result_type", {"base": "x"}))
    add(
        "result-type-base",
        lambda d: d["nodes"][0].__setitem__(
            "result_type", {"base": "", "qualifier": "series", "nullable": True}
        ),
    )
    add(
        "result-type-qualifier",
        lambda d: d["nodes"][0].__setitem__(
            "result_type", {"base": "x", "qualifier": "bad", "nullable": True}
        ),
    )
    add(
        "result-type-nullable",
        lambda d: d["nodes"][0].__setitem__(
            "result_type", {"base": "x", "qualifier": "series", "nullable": 1}
        ),
    )
    add("required-op-remove", lambda d: d["required_operations"].pop())
    add("required-op-unknown", lambda d: d["required_operations"].append("unknown"))
    add(
        "required-op-duplicate",
        lambda d: d["required_operations"].append(d["required_operations"][0]),
    )
    add("required-op-unsorted", lambda d: d["required_operations"].reverse())
    add("capability-unknown", lambda d: d["required_capabilities"].append("unknown"))
    add(
        "capability-duplicate",
        lambda d: d["required_capabilities"].append(d["required_capabilities"][0]),
    )
    add("capability-unsorted", lambda d: d["required_capabilities"].reverse())
    add("nodes-not-list", lambda d: d.__setitem__("nodes", {}))
    add("content-hash", lambda d: d.__setitem__("content_hash", _bad_hash(12)), reseal=False)
    return mutants


def artifact_mutants(artifact: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    base = copy.deepcopy(dict(artifact))
    mutants: list[tuple[str, dict[str, Any]]] = []

    def add(name: str, mutate: Callable[[dict[str, Any]], None], reseal: bool = True) -> None:
        candidate = copy.deepcopy(base)
        mutate(candidate)
        mutants.append((name, _seal(candidate) if reseal else candidate))

    add("schema-id", lambda d: d.__setitem__("schema_id", "wrong"))
    add("schema-version", lambda d: d.__setitem__("schema_version", "2"))
    add("producer-name", lambda d: d["producer"].__setitem__("name", "other"))
    add("producer-version", lambda d: d["producer"].__setitem__("version", "0"))
    add("producer-commit", lambda d: d["producer"].__setitem__("commit", "bad"))
    add(
        "producer-state",
        lambda d: d["producer"].__setitem__("source_state", "UNCOMMITTED_LOCAL_BUILD"),
    )
    add(
        "build-identity-stack",
        lambda d: d["build_identity"].__setitem__("stack_manifest_hash", _bad_hash(27)),
    )
    add("lowering-pack-id", lambda d: d.__setitem__("lowering_pack_id", "wrong"))
    add("target-abi-id", lambda d: d.__setitem__("target_abi_id", "wrong"))
    add("visual-policy", lambda d: d.__setitem__("visual_projection_policy", "OPTIONAL"))
    add("bundle-hash", lambda d: d.__setitem__("bundle_hash", "bad"))
    add("source-hash", lambda d: d.__setitem__("source_hash", "bad"))
    add("catalog-hash", lambda d: d.__setitem__("catalog_hash", "bad"))
    add("plan-hash", lambda d: d.__setitem__("lowering_plan_hash", _bad_hash(21)))
    add("target-hash", lambda d: d.__setitem__("target_manifest_hash", _bad_hash(22)))
    add("module-hash", lambda d: d.__setitem__("emitted_module_hash", _bad_hash(23)))
    add("map-hash", lambda d: d.__setitem__("source_map_hash", _bad_hash(24)))
    add("version-zero", lambda d: d["version_context"].__setitem__("pine_version", 0))
    add(
        "version-catalog", lambda d: d["version_context"].__setitem__("catalog_hash", _bad_hash(25))
    )
    add("entry-module", lambda d: d["entrypoint"].__setitem__("module", "bad-name"))
    add("entry-class", lambda d: d["entrypoint"].__setitem__("class", "Other"))
    add("operations-remove", lambda d: d["required_operations"].pop())
    add(
        "operations-duplicate",
        lambda d: d["required_operations"].append(d["required_operations"][0]),
    )
    add("operations-unsorted", lambda d: d["required_operations"].reverse())
    add("capabilities-remove", lambda d: d["required_capabilities"].pop())
    add(
        "capabilities-duplicate",
        lambda d: d["required_capabilities"].append(d["required_capabilities"][0]),
    )
    add("imports-compiler", lambda d: d["import_manifest"].append("ast2python"))
    add("imports-duplicate", lambda d: d["import_manifest"].append(d["import_manifest"][0]))
    add(
        "projection-source",
        lambda d: d["projection_proof"].__setitem__(
            "source_node_count", d["projection_proof"]["source_node_count"] + 1
        ),
    )
    add(
        "projection-disposition",
        lambda d: d["projection_proof"]["disposition_counts"].__setitem__(
            "EMITTED", d["projection_proof"]["disposition_counts"]["EMITTED"] - 1
        ),
    )
    add(
        "projection-ir",
        lambda d: d["projection_proof"].__setitem__(
            "ir_node_count", d["projection_proof"]["ir_node_count"] - 1
        ),
    )
    add(
        "projection-map",
        lambda d: d["projection_proof"].__setitem__(
            "source_map_entry_count", d["projection_proof"]["source_map_entry_count"] - 1
        ),
    )
    add(
        "projection-coverage",
        lambda d: d["projection_proof"].__setitem__("mapped_ir_coverage", False),
    )
    add("release-pine2ast", lambda d: d["release_acceptance"].__setitem__("pine2ast_rc6", "PASS"))
    add("release-tv", lambda d: d["release_acceptance"].__setitem__("tradingview_oracle", "PASS"))
    add("field-extra", lambda d: d.__setitem__("extra", 1))
    add("content-hash", lambda d: d.__setitem__("content_hash", _bad_hash(26)), reseal=False)
    return mutants


def run_bundle_mutations(bundle: Mapping[str, Any]) -> tuple[MutationResult, ...]:
    service = BundleAdmissionService()
    results: list[MutationResult] = []
    for mutation_id, candidate in bundle_mutants(bundle):
        try:
            service.admit(candidate)
        except BundleAdmissionError as exc:
            results.append(MutationResult("bundle", mutation_id, True, exc.finding.code))
        except Exception as exc:  # producer verifier exception is still a killed mutant
            results.append(MutationResult("bundle", mutation_id, True, type(exc).__name__))
        else:
            results.append(MutationResult("bundle", mutation_id, False, None))
    return tuple(results)


def run_plan_mutations(plan: LoweringPlan, target: TargetManifest) -> tuple[MutationResult, ...]:
    results: list[MutationResult] = []
    for mutation_id, candidate in plan_mutants(plan):
        try:
            verify_lowering_plan_payload(candidate, target=target)
        except BundleInvariantError as exc:
            results.append(MutationResult("plan", mutation_id, True, exc.finding.code))
        except Exception as exc:
            results.append(MutationResult("plan", mutation_id, True, type(exc).__name__))
        else:
            results.append(MutationResult("plan", mutation_id, False, None))
    return tuple(results)


def run_artifact_mutations(
    artifact: Mapping[str, Any],
    *,
    plan: LoweringPlan,
    target: TargetManifest,
    emitted: EmittedPythonModule,
) -> tuple[MutationResult, ...]:
    results: list[MutationResult] = []
    for mutation_id, candidate in artifact_mutants(artifact):
        try:
            verify_generated_artifact_v3(candidate, plan=plan, target=target, emitted=emitted)
        except BundleInvariantError as exc:
            results.append(MutationResult("artifact", mutation_id, True, exc.finding.code))
        except Exception as exc:
            results.append(MutationResult("artifact", mutation_id, True, type(exc).__name__))
        else:
            results.append(MutationResult("artifact", mutation_id, False, None))
    return tuple(results)
