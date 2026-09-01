#!/usr/bin/env python3
"""Run non-vacuous property, fuzz, and performance release gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ast2python.hardening.fuzz import run_deterministic_fuzz
from ast2python.hardening.performance import run_performance_gate
from ast2python.hardening.properties import run_property_gate

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_hardening_gates(
    *,
    manifest_path: Path,
    output_path: Path,
    fuzz_cases: int,
    performance_samples: int,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("normative corpus is empty")
    bundle_paths = [REPO_ROOT / str(case["consumer_bundle"]) for case in cases]
    property_report = run_property_gate(bundle_paths)
    fuzz_report = run_deterministic_fuzz(bundle_paths, cases=fuzz_cases).to_dict()
    performance_bundle = max(bundle_paths, key=lambda path: path.stat().st_size)
    performance_report = run_performance_gate(
        performance_bundle,
        samples=performance_samples,
    ).to_dict()
    report = {
        "schema_id": "ast2python.rc6.hardening_gates.v1",
        "ok": bool(property_report["ok"] and fuzz_report["ok"] and performance_report["ok"]),
        "property": property_report,
        "fuzz": fuzz_report,
        "performance": performance_report,
        "performance_bundle": performance_bundle.relative_to(REPO_ROOT).as_posix(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "tests" / "corpus" / "manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "evidence" / "hardening-gates.json",
    )
    parser.add_argument("--fuzz-cases", type=int, default=10_000)
    parser.add_argument("--performance-samples", type=int, default=20)
    args = parser.parse_args()
    report = run_hardening_gates(
        manifest_path=args.manifest.resolve(),
        output_path=args.output.resolve(),
        fuzz_cases=args.fuzz_cases,
        performance_samples=args.performance_samples,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
