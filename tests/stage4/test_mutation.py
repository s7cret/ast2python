from __future__ import annotations

import json
from pathlib import Path

from ast2python import compile_reference_consumer_bundle as compile_consumer_bundle
from ast2python import load_reference_target_manifest
from ast2python.hardening import run_artifact_mutations, run_bundle_mutations, run_plan_mutations

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "fixtures" / "consumer" / "pine-v6-consumer-bundle.json"


def test_stage4_mutation_thresholds() -> None:
    target = load_reference_target_manifest()
    result = compile_consumer_bundle(BUNDLE)
    bundle_results = run_bundle_mutations(json.loads(BUNDLE.read_text()))
    plan_results = run_plan_mutations(result.plan, target)
    artifact_results = run_artifact_mutations(
        result.artifact.payload,
        plan=result.plan,
        target=target,
        emitted=result.emitted,
    )
    assert len(bundle_results) >= 40
    assert len(plan_results) >= 40
    assert len(artifact_results) >= 30
    assert all(item.killed for item in bundle_results)
    assert all(item.killed for item in plan_results)
    assert all(item.killed for item in artifact_results)
