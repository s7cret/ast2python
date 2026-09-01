"""CLI for the Ast2Python 5.0.0rc6 third near-final hardening pass."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from ast2python.hardening.release_candidate import (
    build_final_gate,
    build_rc5_differential_status,
    build_source_manifest,
    inspect_git_state,
    inspect_tooling,
    inspect_workflow_action_pins,
    run_command,
    run_syntax_compatibility_matrix,
    sha256_file,
)

RC5_COMMIT = "df6783345ab7105334596b3685206a28e7f7e33e"
RC5_WHEEL_SHA256 = "31ce44ac739acc70841ecd5914c59e7893188e94102a3fca3bea2e95fb66bc34"


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def _bind(payload: dict[str, object], source_root_hash: str) -> dict[str, object]:
    return {**payload, "source_root_hash": source_root_hash}


def run(root: Path, evidence: Path) -> dict[str, object]:
    source_manifest = build_source_manifest(root)
    source_root_hash = str(source_manifest["root_hash"])
    syntax = _bind(run_syntax_compatibility_matrix(root), source_root_hash)
    workflows = _bind(inspect_workflow_action_pins(root), source_root_hash)
    tooling = _bind(inspect_tooling(), source_root_hash)
    tests_command = run_command(
        (sys.executable, "-m", "pytest", "-q"),
        cwd=root,
        env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        timeout=1200,
    )
    tests = {
        "schema_id": "ast2python.rc6.tests.v1",
        "source_root_hash": source_root_hash,
        "ok": tests_command.ok,
        "test_count": sum(
            int(value)
            for value in re.findall(r"(?:^|\s)(\d+) passed(?:\s|$)", tests_command.stdout)
        ),
        "command": tests_command.to_dict(),
    }
    build_command = run_command(
        (
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "-w",
            str(evidence / "dist"),
            ".",
        ),
        cwd=root,
        env={"SOURCE_DATE_EPOCH": "1704067200"},
        timeout=1200,
    )
    built_wheels = tuple(sorted((evidence / "dist").glob("*.whl")))
    built_wheel_sha256 = sha256_file(built_wheels[0]) if len(built_wheels) == 1 else None
    build = {
        "schema_id": "ast2python.rc6.build.v1",
        "source_root_hash": source_root_hash,
        "ok": build_command.ok,
        "artifact_count": len(built_wheels),
        "wheel_sha256": built_wheel_sha256,
        "command": build_command.to_dict(),
    }
    git_state = _bind(inspect_git_state(root), source_root_hash)
    clean_install = {
        "schema_id": "ast2python.rc6.clean_install.v1",
        "source_root_hash": source_root_hash,
        "ok": False,
        "status": "RUN_BY_PACKET_BUILDER_AFTER_WHEEL_CREATION",
        "import_check_count": 0,
        "wheel_sha256": built_wheel_sha256,
    }
    differential = build_rc5_differential_status(
        rc5_commit=RC5_COMMIT,
        rc5_wheel_sha256=RC5_WHEEL_SHA256,
        source_root_hash=source_root_hash,
    )
    differential["source_root_hash"] = source_root_hash
    for name, payload in (
        ("source-manifest.json", source_manifest),
        ("git-state.json", git_state),
        ("python-syntax-matrix.json", syntax),
        ("workflow-action-pins.json", workflows),
        ("tooling-inventory.json", tooling),
        ("tests.json", tests),
        ("build.json", build),
        ("rc5-differential.json", differential),
    ):
        _write(evidence / name, payload)
    gate = build_final_gate(
        source_manifest=source_manifest,
        git_state=git_state,
        syntax_matrix=syntax,
        workflow_pins=workflows,
        tests=tests,
        build=build,
        clean_install=clean_install,
        rc5_differential=differential,
        tooling=tooling,
    )
    _write(evidence / "FINAL_GATE.partial.json", gate)
    return gate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ast2python.hardening.pass3")
    parser.add_argument("--root", default=".")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)
    gate = run(Path(args.root).resolve(), Path(args.evidence).resolve())
    print(json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate["local_candidate_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
