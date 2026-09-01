"""Release-candidate hardening helpers for Ast2Python 5.0.0rc6.

The module is deliberately standard-library only.  It records what was actually
executed and never upgrades an unavailable external gate to PASS.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_IDENTITY_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ACTION_REF_RE = re.compile(r"^(?P<repo>[^\s@]+)@(?P<ref>[^\s#]+)$")
_FULL_ACTION_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
    }
)
_EXCLUDED_NAMES = frozenset({".coverage", "coverage.json", "coverage.xml"})
_RC5_COMMIT = "df6783345ab7105334596b3685206a28e7f7e33e"
_RC5_WHEEL_SHA256 = "31ce44ac739acc70841ecd5914c59e7893188e94102a3fca3bea2e95fb66bc34"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _is_excluded(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    if any(
        part in _EXCLUDED_PARTS or part.endswith((".egg-info", ".dist-info"))
        for part in relative.parts
    ):
        return True
    return path.name in _EXCLUDED_NAMES or path.suffix in {".pyc", ".pyo"}


def iter_manifest_files(root: str | Path) -> tuple[Path, ...]:
    root_path = Path(root).resolve()
    return tuple(
        path
        for path in sorted(root_path.rglob("*"))
        if path.is_file() and not _is_excluded(root_path, path)
    )


def build_source_manifest(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    files = []
    for path in iter_manifest_files(root_path):
        relative = path.relative_to(root_path).as_posix()
        files.append({"path": relative, "size": path.stat().st_size, "sha256": sha256_file(path)})
    body: dict[str, Any] = {
        "schema_id": "ast2python.rc6.source_manifest.v1",
        "root_name": root_path.name,
        "file_count": len(files),
        "files": files,
    }
    body["root_hash"] = "sha256:" + sha256_bytes(_canonical_json(body))
    return body


def verify_source_manifest(root: str | Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    root_path = Path(root).resolve()
    expected = build_source_manifest(root_path)
    findings: list[dict[str, Any]] = []
    if manifest.get("schema_id") != expected["schema_id"]:
        findings.append({"code": "MANIFEST_SCHEMA", "actual": manifest.get("schema_id")})
    expected_rows = {row["path"]: row for row in expected["files"]}
    supplied = manifest.get("files")
    if not isinstance(supplied, list):
        findings.append({"code": "MANIFEST_FILES_TYPE"})
        supplied_rows: dict[str, Mapping[str, Any]] = {}
    else:
        supplied_rows = {
            str(row.get("path")): row
            for row in supplied
            if isinstance(row, Mapping) and isinstance(row.get("path"), str)
        }
    missing = sorted(set(expected_rows) - set(supplied_rows))
    extra = sorted(set(supplied_rows) - set(expected_rows))
    if missing:
        findings.append({"code": "MANIFEST_MISSING", "paths": missing})
    if extra:
        findings.append({"code": "MANIFEST_EXTRA", "paths": extra})
    for name in sorted(set(expected_rows) & set(supplied_rows)):
        actual = supplied_rows[name]
        expected_row = expected_rows[name]
        if (
            actual.get("size") != expected_row["size"]
            or actual.get("sha256") != expected_row["sha256"]
        ):
            findings.append(
                {
                    "code": "MANIFEST_MISMATCH",
                    "path": name,
                    "expected": expected_row,
                    "actual": dict(actual),
                }
            )
    if manifest.get("root_hash") != expected["root_hash"]:
        findings.append(
            {
                "code": "MANIFEST_ROOT_HASH",
                "expected": expected["root_hash"],
                "actual": manifest.get("root_hash"),
            }
        )
    return {
        "schema_id": "ast2python.rc6.source_manifest_verification.v1",
        "ok": not findings,
        "expected_root_hash": expected["root_hash"],
        "findings": findings,
    }


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: tuple[str, ...]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    started_at_utc: str
    finished_at_utc: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "python": sys.version,
        }


def run_command(
    argv: Sequence[str],
    *,
    cwd: str | Path,
    env: Mapping[str, str] | None = None,
    timeout: int = 600,
) -> CommandResult:
    started = _utc_now()
    merged_env = os.environ.copy()
    if env:
        merged_env.update({str(key): str(value) for key, value in env.items()})
    completed = subprocess.run(
        list(argv),
        cwd=Path(cwd),
        env=merged_env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        argv=tuple(str(item) for item in argv),
        cwd=str(Path(cwd).resolve()),
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        started_at_utc=started,
        finished_at_utc=_utc_now(),
    )


def inspect_git_state(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()

    def git(*args: str) -> CommandResult:
        return run_command(("git", *args), cwd=root_path, timeout=60)

    inside = git("rev-parse", "--is-inside-work-tree")
    if not inside.ok or inside.stdout.strip() != "true":
        return {
            "schema_id": "ast2python.rc6.git_state.v1",
            "ok": False,
            "status": "NOT_A_GIT_WORKTREE",
            "root": str(root_path),
            "findings": [inside.to_dict()],
        }
    commit_result = git("rev-parse", "HEAD")
    tree_result = git("rev-parse", "HEAD^{tree}")
    branch_result = git("symbolic-ref", "--short", "-q", "HEAD")
    status_result = git("status", "--porcelain=v1", "--untracked-files=all")
    commit = commit_result.stdout.strip()
    tree = tree_result.stdout.strip()
    status_lines = tuple(line for line in status_result.stdout.splitlines() if line)
    tracked = tuple(line for line in status_lines if not line.startswith("??"))
    untracked = tuple(line for line in status_lines if line.startswith("??"))
    findings: list[dict[str, Any]] = []
    if not _GIT_SHA_RE.fullmatch(commit):
        findings.append({"code": "GIT_COMMIT", "value": commit})
    if not _GIT_SHA_RE.fullmatch(tree):
        findings.append({"code": "GIT_TREE", "value": tree})
    if tracked:
        findings.append({"code": "GIT_TRACKED_DIRTY", "entries": list(tracked)})
    if untracked:
        findings.append({"code": "GIT_UNTRACKED", "entries": list(untracked)})
    return {
        "schema_id": "ast2python.rc6.git_state.v1",
        "ok": not findings,
        "status": "CLEAN_COMMIT" if not findings else "DIRTY_OR_INVALID",
        "root": str(root_path),
        "commit": commit,
        "tree": tree,
        "branch": branch_result.stdout.strip() or None,
        "detached": not branch_result.ok,
        "tracked_changes": len(tracked),
        "untracked_files": len(untracked),
        "findings": findings,
    }


def run_syntax_compatibility_matrix(
    root: str | Path,
    *,
    versions: Iterable[int] = (11, 12, 13),
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    paths = tuple(sorted((root_path / "ast2python").rglob("*.py")))
    rows: list[dict[str, Any]] = []
    for minor in versions:
        failures: list[dict[str, Any]] = []
        for path in paths:
            source = path.read_text(encoding="utf-8")
            try:
                ast.parse(source, filename=str(path), feature_version=(3, minor))
            except (SyntaxError, ValueError) as exc:
                failures.append(
                    {
                        "path": path.relative_to(root_path).as_posix(),
                        "detail": str(exc),
                    }
                )
        rows.append(
            {
                "python_version": f"3.{minor}",
                "check_kind": "CPYTHON_AST_FEATURE_VERSION",
                "status": "PASS" if not failures else "FAIL",
                "files_checked": len(paths),
                "failures": failures,
                "runtime_execution": "PASS" if minor == sys.version_info.minor else "NOT_RUN",
            }
        )
    return {
        "schema_id": "ast2python.rc6.python_syntax_matrix.v1",
        "ok": all(row["status"] == "PASS" for row in rows),
        "host_python": sys.version,
        "rows": rows,
        "claim_boundary": (
            "feature_version parsing proves syntax compatibility only; it does not replace an actual "
            "Python 3.11/3.12 runtime test run"
        ),
    }


def inspect_workflow_action_pins(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    workflow_root = root_path / ".github" / "workflows"
    workflows = tuple(sorted(workflow_root.glob("*.y*ml"))) if workflow_root.is_dir() else ()
    uses_rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for path in workflows:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith("uses:") and " uses:" not in f" {stripped}":
                continue
            match = re.search(r"\buses:\s*([^\s#]+)", stripped)
            if match is None:
                continue
            reference = match.group(1).strip("'\"")
            if reference.startswith("./"):
                uses_rows.append(
                    {
                        "path": path.relative_to(root_path).as_posix(),
                        "line": line_no,
                        "reference": reference,
                        "status": "LOCAL_ACTION",
                    }
                )
                continue
            parsed = _ACTION_REF_RE.fullmatch(reference)
            full_sha = (
                parsed is not None
                and _FULL_ACTION_SHA_RE.fullmatch(parsed.group("ref")) is not None
            )
            uses_rows.append(
                {
                    "path": path.relative_to(root_path).as_posix(),
                    "line": line_no,
                    "reference": reference,
                    "status": "PINNED_FULL_SHA" if full_sha else "FLOATING_OR_INVALID",
                }
            )
            if not full_sha:
                findings.append(
                    {
                        "code": "WORKFLOW_ACTION_NOT_PINNED",
                        "path": path.relative_to(root_path).as_posix(),
                        "line": line_no,
                        "reference": reference,
                    }
                )
    if not workflows:
        findings.append({"code": "WORKFLOW_MISSING"})
    if workflows and not uses_rows:
        findings.append({"code": "WORKFLOW_NO_ACTIONS"})
    return {
        "schema_id": "ast2python.rc6.workflow_pin_report.v1",
        "ok": not findings,
        "workflow_count": len(workflows),
        "action_references": uses_rows,
        "findings": findings,
    }


def inspect_tooling() -> dict[str, Any]:
    tools = []
    for name in ("pytest", "coverage", "ruff", "black", "mypy", "setuptools", "wheel"):
        executable = shutil.which(name)
        module = importlib.util.find_spec(name)
        tools.append(
            {
                "name": name,
                "available": bool(executable or module),
                "executable": executable,
                "module": None if module is None else module.name,
            }
        )
    return {
        "schema_id": "ast2python.rc6.tooling_inventory.v1",
        "host_python": sys.version,
        "tools": tools,
    }


def build_rc5_differential_status(
    *,
    rc5_commit: str,
    rc5_wheel_sha256: str,
    executable_evidence: str | Path | None = None,
    source_root_hash: str | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    if not _GIT_SHA_RE.fullmatch(rc5_commit):
        findings.append({"code": "RC5_COMMIT_FORMAT"})
    if not _SHA256_RE.fullmatch(rc5_wheel_sha256):
        findings.append({"code": "RC5_WHEEL_HASH_FORMAT"})
    evidence_path = None if executable_evidence is None else Path(executable_evidence)
    if evidence_path is None or not evidence_path.is_file():
        return {
            "schema_id": "ast2python.rc6.rc5_differential.v1",
            "ok": False,
            "status": "NOT_RUN_EXACT_RC5_EXECUTABLE_ARTIFACT_UNAVAILABLE",
            "rc5_commit": rc5_commit,
            "rc5_wheel_sha256": rc5_wheel_sha256,
            "regressions": None,
            "case_count": None,
            "source_root_hash": source_root_hash,
            "findings": findings,
        }
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    regressions = payload.get("regressions")
    case_count = payload.get("case_count")
    if payload.get("schema_id") != "ast2python.rc6.rc5_rc6_differential.v1":
        findings.append({"code": "RC5_EVIDENCE_SCHEMA"})
    if payload.get("rc5_commit") != rc5_commit:
        findings.append({"code": "RC5_EVIDENCE_COMMIT"})
    if payload.get("rc5_wheel_sha256") != rc5_wheel_sha256:
        findings.append({"code": "RC5_EVIDENCE_WHEEL"})
    if type(regressions) is not int or regressions != 0:
        findings.append({"code": "RC5_REGRESSIONS"})
    if type(case_count) is not int or case_count <= 0:
        findings.append({"code": "RC5_CASE_COUNT"})
    ok = payload.get("ok") is True and not findings
    return {
        "schema_id": "ast2python.rc6.rc5_differential.v1",
        "ok": ok,
        "status": "PASS" if ok else "FAIL",
        "rc5_commit": rc5_commit,
        "rc5_wheel_sha256": rc5_wheel_sha256,
        "regressions": regressions,
        "case_count": case_count,
        "source_root_hash": source_root_hash,
        "evidence_sha256": sha256_file(evidence_path),
        "findings": findings,
    }


def _schema_ok(evidence: Mapping[str, Any] | None, schema_id: str) -> bool:
    return isinstance(evidence, Mapping) and evidence.get("schema_id") == schema_id


def _same_root(evidence: Mapping[str, Any] | None, source_root_hash: str) -> bool:
    return isinstance(evidence, Mapping) and evidence.get("source_root_hash") == source_root_hash


def _command_ok(evidence: Mapping[str, Any]) -> bool:
    command = evidence.get("command")
    if command is None:
        return True
    return (
        isinstance(command, Mapping)
        and command.get("ok") is True
        and type(command.get("exit_code")) is int
        and command.get("exit_code") == 0
    )


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def build_final_gate(
    *,
    source_manifest: Mapping[str, Any],
    git_state: Mapping[str, Any],
    syntax_matrix: Mapping[str, Any],
    workflow_pins: Mapping[str, Any],
    tests: Mapping[str, Any],
    build: Mapping[str, Any],
    clean_install: Mapping[str, Any],
    rc5_differential: Mapping[str, Any],
    tooling: Mapping[str, Any],
    exact_pinelib_target: Mapping[str, Any] | None = None,
    hosted_ci: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_root_hash = source_manifest.get("root_hash")
    source_files = source_manifest.get("files")
    source_body = {key: source_manifest[key] for key in source_manifest if key != "root_hash"}
    expected_source_root = "sha256:" + sha256_bytes(_canonical_json(source_body))
    source_ok = bool(
        _schema_ok(source_manifest, "ast2python.rc6.source_manifest.v1")
        and isinstance(source_root_hash, str)
        and _SHA256_IDENTITY_RE.fullmatch(source_root_hash)
        and source_root_hash == expected_source_root
        and isinstance(source_manifest.get("root_name"), str)
        and source_manifest.get("root_name")
        and isinstance(source_files, list)
        and _positive_int(source_manifest.get("file_count"))
        and source_manifest.get("file_count") == len(source_files)
        and all(
            isinstance(row, Mapping)
            and isinstance(row.get("path"), str)
            and bool(row.get("path"))
            and _nonnegative_int(row.get("size"))
            and isinstance(row.get("sha256"), str)
            and _SHA256_RE.fullmatch(row["sha256"])
            for row in source_files
        )
    )
    root = source_root_hash if isinstance(source_root_hash, str) else ""

    git_ok = bool(
        _schema_ok(git_state, "ast2python.rc6.git_state.v1")
        and _same_root(git_state, root)
        and git_state.get("ok") is True
        and isinstance(git_state.get("commit"), str)
        and _GIT_SHA_RE.fullmatch(git_state["commit"])
        and isinstance(git_state.get("tree"), str)
        and _GIT_SHA_RE.fullmatch(git_state["tree"])
        and git_state.get("tracked_changes") == 0
        and git_state.get("untracked_files") == 0
        and _command_ok(git_state)
    )
    syntax_rows = syntax_matrix.get("rows")
    syntax_ok = bool(
        _schema_ok(syntax_matrix, "ast2python.rc6.python_syntax_matrix.v1")
        and _same_root(syntax_matrix, root)
        and syntax_matrix.get("ok") is True
        and isinstance(syntax_rows, list)
        and [row.get("python_version") for row in syntax_rows if isinstance(row, Mapping)]
        == ["3.11", "3.12", "3.13"]
        and all(
            isinstance(row, Mapping)
            and row.get("status") == "PASS"
            and _positive_int(row.get("files_checked"))
            for row in syntax_rows
        )
        and _command_ok(syntax_matrix)
    )
    action_references = workflow_pins.get("action_references")
    workflows_ok = bool(
        _schema_ok(workflow_pins, "ast2python.rc6.workflow_pin_report.v1")
        and _same_root(workflow_pins, root)
        and workflow_pins.get("ok") is True
        and _positive_int(workflow_pins.get("workflow_count"))
        and isinstance(action_references, list)
        and len(action_references) > 0
        and all(
            isinstance(row, Mapping) and row.get("status") in {"PINNED_FULL_SHA", "LOCAL_ACTION"}
            for row in action_references
        )
        and _command_ok(workflow_pins)
    )
    tests_ok = bool(
        _schema_ok(tests, "ast2python.rc6.tests.v1")
        and _same_root(tests, root)
        and tests.get("ok") is True
        and _positive_int(tests.get("test_count"))
        and "command" in tests
        and _command_ok(tests)
    )
    build_wheel_sha256 = build.get("wheel_sha256")
    build_ok = bool(
        _schema_ok(build, "ast2python.rc6.build.v1")
        and _same_root(build, root)
        and build.get("ok") is True
        and _positive_int(build.get("artifact_count"))
        and isinstance(build_wheel_sha256, str)
        and _SHA256_RE.fullmatch(build_wheel_sha256)
        and "command" in build
        and _command_ok(build)
    )
    clean_install_ok = bool(
        _schema_ok(clean_install, "ast2python.rc6.clean_install.v1")
        and _same_root(clean_install, root)
        and clean_install.get("ok") is True
        and _positive_int(clean_install.get("import_check_count"))
        and clean_install.get("wheel_sha256") == build_wheel_sha256
        and "command" in clean_install
        and _command_ok(clean_install)
    )
    tool_rows = tooling.get("tools")
    required_tools = {"pytest", "coverage", "ruff", "black", "mypy", "setuptools", "wheel"}
    available_tools = (
        {
            row.get("name")
            for row in tool_rows
            if isinstance(row, Mapping) and row.get("available") is True
        }
        if isinstance(tool_rows, list)
        else set()
    )
    tooling_ok = bool(
        _schema_ok(tooling, "ast2python.rc6.tooling_inventory.v1")
        and _same_root(tooling, root)
        and isinstance(tool_rows, list)
        and len(tool_rows) > 0
        and required_tools <= available_tools
        and _command_ok(tooling)
    )

    rc5_ok = bool(
        _schema_ok(rc5_differential, "ast2python.rc6.rc5_differential.v1")
        and _same_root(rc5_differential, root)
        and rc5_differential.get("ok") is True
        and rc5_differential.get("rc5_commit") == _RC5_COMMIT
        and rc5_differential.get("rc5_wheel_sha256") == _RC5_WHEEL_SHA256
        and rc5_differential.get("regressions") == 0
        and _positive_int(rc5_differential.get("case_count"))
        and isinstance(rc5_differential.get("evidence_sha256"), str)
        and _SHA256_RE.fullmatch(rc5_differential["evidence_sha256"])
        and _command_ok(rc5_differential)
    )
    exact_target_ok = bool(
        _schema_ok(exact_pinelib_target, "ast2python.rc6.exact_pinelib_target.v1")
        and _same_root(exact_pinelib_target, root)
        and exact_pinelib_target is not None
        and exact_pinelib_target.get("ok") is True
        and exact_pinelib_target.get("release_acceptance") == "EXACT_PINELIB_RC6_ACCEPTED"
        and isinstance(exact_pinelib_target.get("target_manifest_hash"), str)
        and _SHA256_IDENTITY_RE.fullmatch(exact_pinelib_target["target_manifest_hash"])
        and exact_pinelib_target.get("target_manifest_hash")
        == exact_pinelib_target.get("expected_target_manifest_hash")
        and isinstance(exact_pinelib_target.get("wheel_sha256"), str)
        and _SHA256_RE.fullmatch(exact_pinelib_target["wheel_sha256"])
        and exact_pinelib_target.get("wheel_sha256")
        == exact_pinelib_target.get("expected_wheel_sha256")
        and isinstance(exact_pinelib_target.get("commit"), str)
        and _GIT_SHA_RE.fullmatch(exact_pinelib_target["commit"])
        and exact_pinelib_target.get("commit") == exact_pinelib_target.get("expected_commit")
        and _positive_int(exact_pinelib_target.get("case_count"))
        and _command_ok(exact_pinelib_target)
    )
    hosted_common_ok = bool(
        _schema_ok(hosted_ci, "ast2python.rc6.hosted_ci.v1")
        and _same_root(hosted_ci, root)
        and hosted_ci is not None
        and exact_pinelib_target is not None
        and hosted_ci.get("ok") is True
        and hosted_ci.get("source_commit") == git_state.get("commit")
        and isinstance(hosted_ci.get("source_commit"), str)
        and _GIT_SHA_RE.fullmatch(hosted_ci["source_commit"])
        and _positive_int(hosted_ci.get("job_count"))
        and hosted_ci.get("target_manifest_hash")
        == exact_pinelib_target.get("target_manifest_hash")
        and hosted_ci.get("pinelib_wheel_sha256") == exact_pinelib_target.get("wheel_sha256")
        and hosted_ci.get("pinelib_commit") == exact_pinelib_target.get("commit")
        and _command_ok(hosted_ci)
    )
    hosted_python_ok = bool(
        hosted_common_ok
        and hosted_ci is not None
        and hosted_ci.get("python_versions") == ["3.11", "3.12", "3.13"]
    )
    hosted_quality_ok = bool(
        hosted_common_ok and hosted_ci is not None and hosted_ci.get("quality_ok") is True
    )

    local_gates = {
        "source_manifest": source_ok,
        "git_state": git_ok,
        "syntax_matrix": syntax_ok,
        "workflow_pins": workflows_ok,
        "tests": tests_ok,
        "build": build_ok,
        "clean_install": clean_install_ok,
        "tooling": tooling_ok,
    }
    external_gates = {
        "rc5_differential": rc5_ok,
        "exact_pinelib_target": exact_target_ok,
        "hosted_python_3_11_3_12_3_13": hosted_python_ok,
        "hosted_ruff_black_mypy": hosted_quality_ok,
    }
    missing_tools = [row["name"] for row in tooling.get("tools", []) if not row.get("available")]
    local_ok = all(local_gates.values())
    external_ok = all(external_gates.values())
    body: dict[str, Any] = {
        "schema_id": "ast2python.rc6.pass3.final_gate.v1",
        "source_root_hash": source_manifest.get("root_hash"),
        "local_gates": local_gates,
        "external_gates": external_gates,
        "local_candidate_ready": local_ok,
        "overall_release_ready": local_ok and external_ok,
        "missing_local_tools": missing_tools,
        "authorization": {"merge": False, "release": False, "deployment": False},
        "verdict": (
            "PASS_RELEASE_READY_NOT_AUTHORIZED"
            if local_ok and external_ok
            else (
                "PASS_LOCAL_CANDIDATE_EXTERNAL_GATES_PENDING"
                if local_ok
                else "REQUEST_CHANGES_LOCAL_GATES_FAILED"
            )
        ),
    }
    body["content_hash"] = "sha256:" + sha256_bytes(_canonical_json(body))
    return body


__all__ = [
    "CommandResult",
    "build_final_gate",
    "build_rc5_differential_status",
    "build_source_manifest",
    "inspect_git_state",
    "inspect_tooling",
    "inspect_workflow_action_pins",
    "iter_manifest_files",
    "run_command",
    "run_syntax_compatibility_matrix",
    "sha256_file",
    "verify_source_manifest",
]
