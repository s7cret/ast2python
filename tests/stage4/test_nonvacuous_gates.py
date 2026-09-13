from __future__ import annotations

import json
import os
import subprocess
import sys
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
    # Measure real hardening in its CLI process, not inside pytest's coverage tracer.
    # Retain every vector, sample, threshold and output-consistency assertion.
    output = tmp_path / "hardening.json"
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("COV_CORE_", "COVERAGE_"))
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.run_hardening_gates",
            "--manifest",
            str(MANIFEST),
            "--output",
            str(output),
            "--fuzz-cases",
            "90",
            "--performance-samples",
            "2",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["ok"] is True, report
    assert report["fuzz"]["requested_cases"] == 90
    assert report["fuzz"]["executed_cases"] == 90
    assert report["fuzz"]["shape_counts"]
    assert report["property"]["checked_bundles"] == 22
    assert report["performance"]["samples"] == 2
    assert json.loads(output.read_text(encoding="utf-8")) == report
