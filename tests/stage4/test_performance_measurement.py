from __future__ import annotations

import tracemalloc
from pathlib import Path

import pytest

from ast2python.errors import BundleInvariantError
from ast2python.hardening import performance

BUNDLE = Path(__file__).resolve().parents[1] / "corpus/v6/v6-strategy-orders.bundle.json"


def test_latency_samples_are_untraced_and_memory_runs_real_pipeline(monkeypatch) -> None:
    clock_states: list[bool] = []
    admission_states: list[bool] = []
    artifact_states: list[bool] = []
    clock = performance.time.perf_counter_ns
    admit = performance.BundleAdmissionService.admit
    artifact = performance.build_generated_artifact_v3

    def observed_clock():
        clock_states.append(tracemalloc.is_tracing())
        return clock()

    def observed_admit(self, *args, **kwargs):
        admission_states.append(tracemalloc.is_tracing())
        return admit(self, *args, **kwargs)

    def observed_artifact(*args, **kwargs):
        artifact_states.append(tracemalloc.is_tracing())
        return artifact(*args, **kwargs)

    monkeypatch.setattr(performance.time, "perf_counter_ns", observed_clock)
    monkeypatch.setattr(performance.BundleAdmissionService, "admit", observed_admit)
    monkeypatch.setattr(performance, "build_generated_artifact_v3", observed_artifact)
    report = performance.run_performance_gate(BUNDLE, samples=2)
    assert clock_states and not any(clock_states)
    assert admission_states == [False, False, True, True]
    assert artifact_states == admission_states
    assert report.samples == 2
    assert report.node_count == 36
    assert report.peak_bytes > 0
    assert set(report.median_ms) == {"admission", "ir_build", "ir_validate", "emission", "artifact"}
    assert report.hard_ceilings_ms_per_node == {
        "admission": 10.0,
        "ir_build": 4.0,
        "ir_validate": 4.0,
        "emission": 6.0,
        "artifact": 4.0,
    }
    assert not tracemalloc.is_tracing()


def test_performance_gate_does_not_disable_caller_memory_tracing() -> None:
    tracemalloc.start()
    try:
        with pytest.raises(BundleInvariantError, match="A2P_PERFORMANCE_TRACING"):
            performance.run_performance_gate(BUNDLE, samples=1)
        assert tracemalloc.is_tracing()
    finally:
        tracemalloc.stop()


def test_memory_pass_cleans_up_tracing_on_failure(monkeypatch) -> None:
    admit = performance.BundleAdmissionService.admit

    def fail_memory_pass(self, *args, **kwargs):
        if tracemalloc.is_tracing():
            raise RuntimeError("memory pass failed")
        return admit(self, *args, **kwargs)

    monkeypatch.setattr(performance.BundleAdmissionService, "admit", fail_memory_pass)
    try:
        with pytest.raises(RuntimeError, match="memory pass failed"):
            performance.run_performance_gate(BUNDLE, samples=1)
        assert not tracemalloc.is_tracing()
    finally:
        tracemalloc.stop()
