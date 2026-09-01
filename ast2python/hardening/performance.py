from __future__ import annotations

import statistics
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ast2python.admission import BundleAdmissionService
from ast2python.artifacts import build_generated_artifact_v3
from ast2python.emission import emit_python_module
from ast2python.errors import BundleInvariantError
from ast2python.lowering import (
    build_lowering_plan,
    load_reference_target_manifest,
    validate_lowering_plan,
)
from ast2python.session import CompilationSession


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    samples: int
    node_count: int
    median_ms: dict[str, float]
    peak_bytes: int
    hard_ceilings_ms_per_node: dict[str, float]
    violations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": "ast2python.stage4.performance.v1",
            "ok": self.ok,
            "samples": self.samples,
            "node_count": self.node_count,
            "median_ms": self.median_ms,
            "peak_bytes": self.peak_bytes,
            "hard_ceilings_ms_per_node": self.hard_ceilings_ms_per_node,
            "violations": list(self.violations),
        }


def run_performance_gate(bundle_path: str | Path, *, samples: int = 20) -> PerformanceReport:
    if samples < 1:
        raise BundleInvariantError(
            "A2P_PERFORMANCE_SAMPLES", "performance samples must be positive"
        )
    target = load_reference_target_manifest()
    service = BundleAdmissionService()
    timings: dict[str, list[float]] = {
        name: [] for name in ("admission", "ir_build", "ir_validate", "emission", "artifact")
    }
    peak = 0
    node_count = 0
    for _ in range(samples):
        tracemalloc.start()
        start = time.perf_counter_ns()
        admitted = service.admit(Path(bundle_path))
        timings["admission"].append((time.perf_counter_ns() - start) / 1_000_000)
        session = CompilationSession(admitted)
        start = time.perf_counter_ns()
        plan = build_lowering_plan(session, target)
        timings["ir_build"].append((time.perf_counter_ns() - start) / 1_000_000)
        start = time.perf_counter_ns()
        validate_lowering_plan(plan, target)
        timings["ir_validate"].append((time.perf_counter_ns() - start) / 1_000_000)
        start = time.perf_counter_ns()
        emitted = emit_python_module(plan, target)
        timings["emission"].append((time.perf_counter_ns() - start) / 1_000_000)
        start = time.perf_counter_ns()
        build_generated_artifact_v3(
            bundle_hash=admitted.content_hash,
            source_hash=str(admitted.source["source_hash"]),
            version_context=admitted.version_context.to_dict(),
            plan=plan,
            target=target,
            emitted=emitted,
            producer_commit="a" * 40,
            ast_hash=str(admitted.artifacts["ast_hash"]),
            semantic_facts_hash=str(admitted.artifacts["semantic_facts_hash"]),
            node_index_hash=str(admitted.artifacts["node_index_hash"]),
        )
        timings["artifact"].append((time.perf_counter_ns() - start) / 1_000_000)
        _, current_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak = max(peak, current_peak)
        node_count = len(plan.nodes)
    medians = {name: round(statistics.median(values), 6) for name, values in timings.items()}
    ceilings = {
        "admission": 10.0,
        "ir_build": 4.0,
        "ir_validate": 4.0,
        "emission": 6.0,
        "artifact": 4.0,
    }
    violations = tuple(
        name for name, median in medians.items() if median / max(node_count, 1) > ceilings[name]
    )
    if peak > 256 * 1024 * 1024:
        violations += ("peak_memory",)
    return PerformanceReport(samples, node_count, medians, peak, ceilings, violations)
