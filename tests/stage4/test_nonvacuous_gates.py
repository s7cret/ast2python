from __future__ import annotations

import json
from pathlib import Path

import pytest

from ast2python.errors import BundleInvariantError
from ast2python.hardening.fuzz import run_deterministic_fuzz
from ast2python.hardening.performance import run_performance_gate
from ast2python.hardening.properties import run_property_gate

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests" / "corpus" / "manifest.json"
V6_BUNDLE = ROOT / "tests" / "corpus" / "v6" / "v6-strategy-orders.bundle.json"


def test_fuzz_gate_rejects_zero_vectors() -> None:
    with pytest.raises(BundleInvariantError, match="A2P_FUZZ_INPUTS"):
        run_deterministic_fuzz([], cases=1)
    with pytest.raises(BundleInvariantError, match="A2P_FUZZ_CASES"):
        run_deterministic_fuzz([V6_BUNDLE], cases=0)


def test_property_gate_rejects_empty_input() -> None:
    report = run_property_gate([])
    assert report["ok"] is False
    assert report["checked_bundles"] == 0
    assert {finding["code"] for finding in report["findings"]} == {"A2P_PROPERTY_INPUTS"}


def test_performance_gate_rejects_zero_samples() -> None:
    with pytest.raises(BundleInvariantError, match="A2P_PERFORMANCE_SAMPLES"):
        run_performance_gate(V6_BUNDLE, samples=0)


def test_enforced_hardening_tool_runs_real_vectors(tmp_path: Path) -> None:
    from tools.run_hardening_gates import run_hardening_gates

    output = tmp_path / "hardening.json"
    report = run_hardening_gates(
        manifest_path=MANIFEST,
        output_path=output,
        fuzz_cases=90,
        performance_samples=2,
    )
    assert report["ok"] is True
    assert report["fuzz"]["requested_cases"] == 90
    assert report["fuzz"]["executed_cases"] == 90
    assert report["fuzz"]["shape_counts"]
    assert report["property"]["checked_bundles"] == 22
    assert report["performance"]["samples"] == 2
    assert json.loads(output.read_text(encoding="utf-8")) == report
