from __future__ import annotations

from pathlib import Path

from ast2python.hardening.differential import run_version_differential
from ast2python.hardening.security import run_security_gate

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "fixtures" / "consumer" / "pine-v6-consumer-bundle.json"


def test_twenty_or_more_adjacent_version_pairs() -> None:
    cases = run_version_differential()
    assert len(cases) >= 20
    assert all(case.passed for case in cases)
    assert any(case.left_opcode != case.right_opcode for case in cases)


def test_security_gate() -> None:
    report = run_security_gate(BUNDLE)
    assert report["ok"] is True
    assert report["findings"] == []
    assert report["environment_keys_embedded"] == []
