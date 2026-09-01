#!/usr/bin/env python3
"""Independent package/provenance audit for an extracted pass-3 packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and "" not in path.parts


def verify_sums(root: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    sums = root / "SHA256SUMS"
    if not sums.is_file():
        return [{"code": "SHA256SUMS_MISSING"}]
    for line_no, line in enumerate(sums.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            findings.append({"code": "SHA256SUMS_FORMAT", "line": line_no})
            continue
        expected, relative = match.groups()
        path = root / relative
        if not path.is_file():
            findings.append({"code": "SHA256SUMS_FILE_MISSING", "path": relative})
        elif sha256(path) != expected:
            findings.append({"code": "SHA256SUMS_MISMATCH", "path": relative})
    return findings


def audit(packet: Path) -> dict[str, object]:
    findings = verify_sums(packet)
    wheel_paths = tuple(sorted((packet / "artifacts").glob("*.whl")))
    if len(wheel_paths) != 1:
        findings.append({"code": "WHEEL_COUNT", "actual": len(wheel_paths)})
    else:
        wheel = wheel_paths[0]
        try:
            with zipfile.ZipFile(wheel) as archive:
                bad = archive.testzip()
                if bad is not None:
                    findings.append({"code": "WHEEL_ZIP", "path": bad})
                names = archive.namelist()
                if not all(safe_member(name) for name in names):
                    findings.append({"code": "WHEEL_PATH"})
                records = [name for name in names if name.endswith(".dist-info/RECORD")]
                if len(records) != 1:
                    findings.append({"code": "WHEEL_RECORD_COUNT", "actual": len(records)})
        except zipfile.BadZipFile:
            findings.append({"code": "WHEEL_BAD_ZIP"})
    identity_path = packet / "provenance" / "source-identity.json"
    if not identity_path.is_file():
        findings.append({"code": "SOURCE_IDENTITY_MISSING"})
        identity = {}
    else:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        if not re.fullmatch(r"[0-9a-f]{40}", str(identity.get("commit", ""))):
            findings.append({"code": "SOURCE_COMMIT"})
        if not re.fullmatch(r"[0-9a-f]{40}", str(identity.get("tree", ""))):
            findings.append({"code": "SOURCE_TREE"})
        if identity.get("source_state") != "LOCAL_COMMIT_PINNED":
            findings.append({"code": "SOURCE_STATE"})
    bundle_path = packet / "provenance" / "ast2python-5.0.0rc6-pass3.git.bundle"
    if not bundle_path.is_file():
        findings.append({"code": "GIT_BUNDLE_MISSING"})
    else:
        with tempfile.TemporaryDirectory(prefix="a2p-bundle-audit-") as temporary:
            clone = Path(temporary) / "repo"
            completed = subprocess.run(
                ["git", "clone", "--quiet", str(bundle_path), str(clone)],
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                findings.append(
                    {
                        "code": "GIT_BUNDLE_CLONE",
                        "exit_code": completed.returncode,
                        "stderr": completed.stderr,
                    }
                )
            elif identity and subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=clone, text=True
            ).strip() != identity.get("commit"):
                findings.append({"code": "GIT_BUNDLE_COMMIT"})
    gate_path = packet / "FINAL_GATE.json"
    if not gate_path.is_file():
        findings.append({"code": "FINAL_GATE_MISSING"})
        gate = {}
    else:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        if gate.get("authorization") != {"merge": False, "release": False, "deployment": False}:
            findings.append({"code": "AUTHORIZATION_BOUNDARY"})
    return {
        "schema_id": "ast2python.rc6.pass3.independent_provenance_audit.v1",
        "ok": not findings,
        "packet": str(packet.resolve()),
        "file_count": sum(1 for path in packet.rglob("*") if path.is_file()),
        "wheel_count": len(wheel_paths),
        "source_commit": identity.get("commit"),
        "gate_verdict": gate.get("verdict"),
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
