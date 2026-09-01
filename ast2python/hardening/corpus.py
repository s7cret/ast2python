from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ast2python.compiler import compile_reference_consumer_bundle as compile_consumer_bundle
from ast2python.errors import BundleInvariantError


@dataclass(frozen=True, slots=True)
class CorpusCaseResult:
    case_id: str
    pine_version: int
    passed: bool
    mismatches: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "pine_version": self.pine_version,
            "passed": self.passed,
            "mismatches": list(self.mismatches),
        }


def verify_normative_corpus(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_id") != "ast2python.stage4.normative_corpus.v1":
        raise BundleInvariantError("A2P_CORPUS_SCHEMA", "unsupported normative corpus schema")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise BundleInvariantError("A2P_CORPUS_CASES", "normative corpus must contain cases")
    results: list[CorpusCaseResult] = []
    seen: set[str] = set()
    versions: set[int] = set()
    for row in cases:
        if not isinstance(row, dict):
            raise BundleInvariantError("A2P_CORPUS_ROW", "corpus rows must be objects")
        case_id = row.get("case_id")
        version = row.get("pine_version")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise BundleInvariantError("A2P_CORPUS_ID", "corpus case IDs must be unique")
        if type(version) is not int or version not in range(1, 7):
            raise BundleInvariantError("A2P_CORPUS_VERSION", "corpus Pine version must be 1..6")
        seen.add(case_id)
        versions.add(version)
        bundle_path = Path(str(row.get("consumer_bundle")))
        if not bundle_path.is_absolute():
            bundle_path = path.parents[2] / bundle_path
        module_name = row.get("module_name")
        if not isinstance(module_name, str) or not module_name:
            raise BundleInvariantError("A2P_CORPUS_MODULE", "corpus module_name is required")
        result = compile_consumer_bundle(
            bundle_path, module_name=module_name, producer_commit="a" * 40
        )
        actual = {
            "consumer_bundle_hash": result.plan.bundle_hash,
            "catalog_hash": result.plan.catalog_hash,
            "expected_ir_hash": result.plan.content_hash,
            "expected_emitted_module_hash": result.emitted.code_hash,
            "expected_source_map_hash": result.emitted.source_map.content_hash,
            "expected_artifact_hash": result.artifact.payload["content_hash"],
            "required_operations": sorted(result.plan.required_operations),
            "required_capabilities": sorted(result.plan.required_capabilities),
        }
        mismatches = tuple(key for key, value in actual.items() if row.get(key) != value)
        if result.plan.pine_version != version:
            mismatches += ("pine_version",)
        results.append(CorpusCaseResult(case_id, version, not mismatches, mismatches))
    return {
        "schema_id": "ast2python.stage4.corpus_verification.v1",
        "ok": all(item.passed for item in results) and versions == set(range(1, 7)),
        "case_count": len(results),
        "versions": sorted(versions),
        "results": [item.to_dict() for item in results],
    }
