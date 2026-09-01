#!/usr/bin/env python3
"""Fail-closed runner for the exact RC5 -> RC6 differential gate.

This command intentionally refuses to invent results when the exact RC5 wheel is
missing or has the wrong digest.  The corpus adapter is supplied by the release
pipeline after the RC5 wheel has been isolated in its own environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EXPECTED_RC5_SHA256 = "31ce44ac739acc70841ecd5914c59e7893188e94102a3fca3bea2e95fb66bc34"
EXPECTED_RC5_COMMIT = "df6783345ab7105334596b3685206a28e7f7e33e"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rc5-wheel", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--classified-results", required=True)
    args = parser.parse_args(argv)
    wheel = Path(args.rc5_wheel)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    findings: list[dict[str, object]] = []
    if not wheel.is_file():
        findings.append({"code": "RC5_WHEEL_MISSING", "path": str(wheel)})
    elif sha256(wheel) != EXPECTED_RC5_SHA256:
        findings.append(
            {
                "code": "RC5_WHEEL_HASH",
                "expected": EXPECTED_RC5_SHA256,
                "actual": sha256(wheel),
            }
        )
    results_path = Path(args.classified_results)
    case_rows: list[object] = []
    if not results_path.is_file():
        findings.append(
            {
                "code": "CLASSIFIED_RESULTS_MISSING",
                "message": "No result is inferred from package import or version metadata alone.",
            }
        )
        results: dict[str, object] = {}
    else:
        results = json.loads(results_path.read_text(encoding="utf-8"))
        allowed = {
            "INTENTIONAL_VERSION_FIX",
            "BUG_FIXED",
            "BREAKING_CONTRACT_CHANGE",
            "REGRESSION",
            "UNCHANGED",
        }
        rows = results.get("cases")
        if not isinstance(rows, list) or not rows:
            findings.append({"code": "DIFFERENTIAL_CASES_EMPTY"})
            case_rows = []
        else:
            case_rows = rows
            for index, row in enumerate(rows):
                if not isinstance(row, dict) or row.get("classification") not in allowed:
                    findings.append({"code": "DIFFERENTIAL_CLASSIFICATION", "index": index})
    regressions = sum(
        1
        for row in case_rows
        if isinstance(row, dict) and row.get("classification") == "REGRESSION"
    )
    ok = not findings and regressions == 0
    payload = {
        "schema_id": "ast2python.rc6.rc5_rc6_differential.v1",
        "ok": ok,
        "status": "PASS" if ok else "BLOCKED_OR_FAILED",
        "rc5_commit": EXPECTED_RC5_COMMIT,
        "rc5_wheel_sha256": EXPECTED_RC5_SHA256,
        "regressions": regressions if not findings else None,
        "case_count": len(case_rows),
        "findings": findings,
        "python": sys.version,
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
