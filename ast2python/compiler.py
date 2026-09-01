from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ast2python.admission.canonical import BundleInput
from ast2python.api import open_compilation_session
from ast2python.artifacts import (
    GeneratedArtifactV3,
    build_generated_artifact_v3,
    verify_generated_artifact_v3,
)
from ast2python.emission import EmittedPythonModule, emit_python_module
from ast2python.errors import BundleInvariantError
from ast2python.lowering import (
    LoweringPlan,
    TargetManifest,
    build_lowering_plan,
    load_reference_target_manifest,
    validate_lowering_plan,
)
from ast2python.mode import CompilationMode


@dataclass(frozen=True, slots=True)
class CompilationResult:
    plan: LoweringPlan
    emitted: EmittedPythonModule
    artifact: GeneratedArtifactV3

    def to_summary(self) -> dict[str, Any]:
        return {
            "pine_version": self.plan.pine_version,
            "bundle_hash": self.plan.bundle_hash,
            "plan_hash": self.plan.content_hash,
            "target_manifest_hash": self.plan.target_manifest_hash,
            "emitted": self.emitted.to_summary(),
            "artifact_hash": self.artifact.payload["content_hash"],
        }


def compile_consumer_bundle(
    source: BundleInput,
    *,
    target: TargetManifest | None = None,
    module_name: str = "generated_pine_script",
    producer_commit: str | None = None,
    expected_pine2ast_commit: str | None = None,
) -> CompilationResult:
    if target is None:
        raise BundleInvariantError(
            "A2P_EXACT_TARGET_REQUIRED",
            "production compilation requires an explicit target manifest",
        )
    selected_target = target
    session = open_compilation_session(
        source,
        mode=CompilationMode.PRODUCTION,
        expected_producer_commit=expected_pine2ast_commit,
    )
    plan = build_lowering_plan(session, selected_target)
    validate_lowering_plan(plan, selected_target)
    emitted = emit_python_module(plan, selected_target, module_name=module_name)
    artifact = build_generated_artifact_v3(
        bundle_hash=session.bundle.content_hash,
        source_hash=str(session.bundle.source["source_hash"]),
        version_context=session.bundle.version_context.to_dict(),
        plan=plan,
        target=selected_target,
        emitted=emitted,
        producer_commit=producer_commit,
        ast_hash=str(session.bundle.artifacts["ast_hash"]),
        semantic_facts_hash=str(session.bundle.artifacts["semantic_facts_hash"]),
        node_index_hash=str(session.bundle.artifacts["node_index_hash"]),
    )
    verify_generated_artifact_v3(
        artifact.payload, plan=plan, target=selected_target, emitted=emitted
    )
    return CompilationResult(plan=plan, emitted=emitted, artifact=artifact)


def compile_reference_consumer_bundle(
    source: BundleInput,
    *,
    module_name: str = "generated_pine_script",
    producer_commit: str | None = None,
    expected_pine2ast_commit: str | None = None,
) -> CompilationResult:
    """Compile against the non-release reference target for tests/hardening only."""

    return compile_consumer_bundle(
        source,
        target=load_reference_target_manifest(),
        module_name=module_name,
        producer_commit=producer_commit or ("a" * 40),
        expected_pine2ast_commit=expected_pine2ast_commit,
    )


def write_compilation_result(result: CompilationResult, output: str | Path) -> dict[str, str]:
    import json

    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    module_path = root / f"{result.emitted.module_name}.py"
    plan_path = root / "lowering-plan.json"
    map_path = root / "source-map.json"
    artifact_path = root / "generated-artifact.json"
    module_path.write_text(result.emitted.code, encoding="utf-8")
    plan_path.write_text(
        json.dumps(result.plan.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    map_path.write_text(
        json.dumps(
            result.emitted.source_map.to_dict(), ensure_ascii=False, sort_keys=True, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    artifact_path.write_text(
        json.dumps(result.artifact.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "module": str(module_path),
        "plan": str(plan_path),
        "source_map": str(map_path),
        "artifact": str(artifact_path),
    }
