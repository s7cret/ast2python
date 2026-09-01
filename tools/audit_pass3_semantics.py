#!/usr/bin/env python3
"""Independent semantic/package audit for an extracted pass-3 packet."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def run(argv: list[str], cwd: Path, timeout: int = 1200) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        argv, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout, check=False
    )
    return {
        "argv": argv,
        "cwd": str(cwd.resolve()),
        "exit_code": result.returncode,
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def audit(packet: Path) -> dict[str, object]:
    source = packet / "source"
    findings: list[dict[str, object]] = []
    tests = run([sys.executable, "-m", "pytest", "-q"], source)
    if not tests["ok"]:
        findings.append({"code": "TESTS", "exit_code": tests["exit_code"]})
    release = run([sys.executable, "-m", "ast2python.release", "--root", "."], source)
    if not release["ok"]:
        findings.append({"code": "RELEASE_REPORT", "exit_code": release["exit_code"]})
    pass3 = run(
        [
            sys.executable,
            "-c",
            (
                "from ast2python.hardening.release_candidate import "
                "run_syntax_compatibility_matrix,inspect_workflow_action_pins;"
                "assert run_syntax_compatibility_matrix('.')['ok'];"
                "assert inspect_workflow_action_pins('.')['ok']"
            ),
        ],
        source,
    )
    if not pass3["ok"]:
        findings.append({"code": "PASS3_STATIC", "exit_code": pass3["exit_code"]})
    return {
        "schema_id": "ast2python.rc6.pass3.independent_semantic_audit.v1",
        "ok": not findings,
        "packet": str(packet.resolve()),
        "tests": tests,
        "release_report": release,
        "pass3_static": pass3,
        "findings": findings,
        "python": sys.version,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("packet", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = audit(args.packet)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
