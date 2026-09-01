from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ast2python.hardening import pass3
from ast2python.hardening.release_candidate import (
    build_final_gate,
    build_rc5_differential_status,
    build_source_manifest,
    inspect_git_state,
    inspect_tooling,
    inspect_workflow_action_pins,
    run_command,
    run_syntax_compatibility_matrix,
    verify_source_manifest,
)

ROOT = Path(__file__).resolve().parents[2]


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "test"], cwd=root, check=True)


def test_source_manifest_detects_changes(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    manifest = build_source_manifest(tmp_path)
    assert verify_source_manifest(tmp_path, manifest)["ok"] is True
    (tmp_path / "a.txt").write_text("b", encoding="utf-8")
    report = verify_source_manifest(tmp_path, manifest)
    assert report["ok"] is False
    assert {row["code"] for row in report["findings"]} >= {
        "MANIFEST_MISMATCH",
        "MANIFEST_ROOT_HASH",
    }


def test_git_state_is_fail_closed_and_clean(tmp_path: Path) -> None:
    assert inspect_git_state(tmp_path)["status"] == "NOT_A_GIT_WORKTREE"
    (tmp_path / "tracked.txt").write_text("x", encoding="utf-8")
    _init_git(tmp_path)
    state = inspect_git_state(tmp_path)
    assert state["ok"] is True
    assert len(state["commit"]) == 40
    (tmp_path / "tracked.txt").write_text("changed", encoding="utf-8")
    assert inspect_git_state(tmp_path)["ok"] is False


def test_git_state_rejects_untracked_files(tmp_path: Path) -> None:
    (tmp_path / "tracked.txt").write_text("x", encoding="utf-8")
    _init_git(tmp_path)
    (tmp_path / "untracked.txt").write_text("x", encoding="utf-8")
    state = inspect_git_state(tmp_path)
    assert state["untracked_files"] == 1
    assert state["ok"] is False


def test_python_syntax_matrix(tmp_path: Path) -> None:
    package = tmp_path / "ast2python"
    package.mkdir()
    (package / "ok.py").write_text("value: int = 1\n", encoding="utf-8")
    report = run_syntax_compatibility_matrix(tmp_path)
    assert report["ok"] is True
    assert [row["python_version"] for row in report["rows"]] == ["3.11", "3.12", "3.13"]
    assert all(row["files_checked"] == 1 for row in report["rows"])


def test_workflow_pin_gate(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "steps:\n  - uses: actions/checkout@" + "a" * 40 + "\n  - uses: ./local\n",
        encoding="utf-8",
    )
    assert inspect_workflow_action_pins(tmp_path)["ok"] is True
    (workflows / "ci.yml").write_text("steps:\n  - uses: actions/checkout@v4\n", encoding="utf-8")
    report = inspect_workflow_action_pins(tmp_path)
    assert report["ok"] is False
    assert report["findings"][0]["code"] == "WORKFLOW_ACTION_NOT_PINNED"


def test_workflow_pin_gate_rejects_missing_and_empty(tmp_path: Path) -> None:
    assert inspect_workflow_action_pins(tmp_path)["findings"][0]["code"] == "WORKFLOW_MISSING"
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: empty\n", encoding="utf-8")
    codes = {row["code"] for row in inspect_workflow_action_pins(tmp_path)["findings"]}
    assert "WORKFLOW_NO_ACTIONS" in codes


def test_rc5_runner_requires_classified_results_argument(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "run_rc5_rc6_differential.py"),
            "--rc5-wheel",
            str(tmp_path / "rc5.whl"),
            "--output",
            str(tmp_path / "output.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "--classified-results" in completed.stderr
    assert "required" in completed.stderr


def test_rc5_workflow_fetches_and_passes_classified_results() -> None:
    workflow = (ROOT / ".github" / "workflows" / "rc6-pass3.yml").read_text(encoding="utf-8")

    assert "classified_results_url:" in workflow
    assert "classified_results_sha256:" in workflow
    assert "curl --fail --location --proto '=https' --tlsv1.2 \"$RESULTS_URL\"" in workflow
    assert "--classified-results .ci-evidence/rc5-rc6-classified-results.json" in workflow


def test_rc5_differential_is_not_inferred(tmp_path: Path) -> None:
    report = build_rc5_differential_status(
        rc5_commit="d" * 40,
        rc5_wheel_sha256="e" * 64,
    )
    assert report["ok"] is False
    assert report["status"] == "NOT_RUN_EXACT_RC5_EXECUTABLE_ARTIFACT_UNAVAILABLE"


def test_rc5_differential_accepts_real_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "diff.json"
    evidence.write_text(
        json.dumps(
            {
                "schema_id": "ast2python.rc6.rc5_rc6_differential.v1",
                "ok": True,
                "rc5_commit": "d" * 40,
                "rc5_wheel_sha256": "e" * 64,
                "regressions": 0,
                "case_count": 2,
            }
        ),
        encoding="utf-8",
    )
    report = build_rc5_differential_status(
        rc5_commit="d" * 40,
        rc5_wheel_sha256="e" * 64,
        executable_evidence=evidence,
    )
    assert report["ok"] is True
    assert report["case_count"] == 2
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["regressions"] = 1
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        build_rc5_differential_status(
            rc5_commit="d" * 40,
            rc5_wheel_sha256="e" * 64,
            executable_evidence=evidence,
        )["ok"]
        is False
    )


def test_command_result(tmp_path: Path) -> None:
    result = run_command(("python", "-c", "print('ok')"), cwd=tmp_path)
    assert result.ok is True
    assert result.to_dict()["stdout"].strip() == "ok"


def test_tooling_inventory_has_expected_names() -> None:
    names = {row["name"] for row in inspect_tooling()["tools"]}
    assert {"pytest", "coverage", "ruff", "black", "mypy", "setuptools", "wheel"} <= names


def test_pass3_binds_produced_evidence_to_source_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    evidence_dir = tmp_path / "evidence"
    root.mkdir()
    source_root_hash = "sha256:" + "a" * 64
    captured: dict[str, Any] = {}

    class FakeCommand:
        ok = True

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

        def to_dict(self) -> dict[str, Any]:
            return {"ok": True, "exit_code": 0, "stdout": self.stdout}

    def fake_command(argv: tuple[str, ...], **_: Any) -> FakeCommand:
        if "wheel" in argv:
            wheel_dir = evidence_dir / "dist"
            wheel_dir.mkdir(parents=True, exist_ok=True)
            (wheel_dir / "ast2python.whl").write_bytes(b"wheel")
            return FakeCommand("built wheel")
        return FakeCommand("226 passed in 1.0s")

    def fake_differential(**kwargs: Any) -> dict[str, Any]:
        captured["differential_kwargs"] = kwargs
        return {"schema_id": "ast2python.rc6.rc5_differential.v1", "ok": False}

    def fake_gate(**kwargs: Any) -> dict[str, Any]:
        captured["gate_kwargs"] = kwargs
        return {"local_candidate_ready": False}

    monkeypatch.setattr(
        pass3,
        "build_source_manifest",
        lambda _: {"schema_id": "ast2python.rc6.source_manifest.v1", "root_hash": source_root_hash},
    )
    monkeypatch.setattr(pass3, "run_syntax_compatibility_matrix", lambda _: {"ok": True})
    monkeypatch.setattr(pass3, "inspect_workflow_action_pins", lambda _: {"ok": True})
    monkeypatch.setattr(pass3, "inspect_tooling", lambda: {"tools": []})
    monkeypatch.setattr(pass3, "inspect_git_state", lambda _: {"ok": True})
    monkeypatch.setattr(pass3, "run_command", fake_command)
    monkeypatch.setattr(pass3, "build_rc5_differential_status", fake_differential)
    monkeypatch.setattr(pass3, "build_final_gate", fake_gate)

    pass3.run(root, evidence_dir)

    gate_inputs = captured["gate_kwargs"]
    for name in (
        "git_state",
        "syntax_matrix",
        "workflow_pins",
        "tests",
        "build",
        "clean_install",
        "rc5_differential",
        "tooling",
    ):
        assert gate_inputs[name]["source_root_hash"] == source_root_hash
    assert gate_inputs["tests"]["test_count"] == 226
    assert gate_inputs["build"]["artifact_count"] == 1
    assert gate_inputs["build"]["wheel_sha256"] == hashlib.sha256(b"wheel").hexdigest()
    assert gate_inputs["clean_install"]["wheel_sha256"] == gate_inputs["build"]["wheel_sha256"]
    assert captured["differential_kwargs"]["source_root_hash"] == source_root_hash


def _base_gate_inputs() -> dict[str, Any]:
    source_manifest: dict[str, Any] = {
        "schema_id": "ast2python.rc6.source_manifest.v1",
        "root_name": "ast2python",
        "file_count": 1,
        "files": [{"path": "pyproject.toml", "size": 1, "sha256": "7" * 64}],
    }
    source_root_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                source_manifest,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    source_manifest["root_hash"] = source_root_hash
    source_commit = "2" * 40
    target_manifest_hash = "sha256:" + "3" * 64
    pinelib_wheel_sha256 = "4" * 64
    pinelib_commit = "5" * 40
    built_wheel_sha256 = "6" * 64
    return {
        "source_manifest": source_manifest,
        "git_state": {
            "schema_id": "ast2python.rc6.git_state.v1",
            "source_root_hash": source_root_hash,
            "ok": True,
            "commit": source_commit,
            "tree": "8" * 40,
            "tracked_changes": 0,
            "untracked_files": 0,
        },
        "syntax_matrix": {
            "schema_id": "ast2python.rc6.python_syntax_matrix.v1",
            "source_root_hash": source_root_hash,
            "ok": True,
            "rows": [
                {"python_version": version, "status": "PASS", "files_checked": 1}
                for version in ("3.11", "3.12", "3.13")
            ],
        },
        "workflow_pins": {
            "schema_id": "ast2python.rc6.workflow_pin_report.v1",
            "source_root_hash": source_root_hash,
            "ok": True,
            "workflow_count": 1,
            "action_references": [{"status": "PINNED_FULL_SHA"}],
        },
        "tests": {
            "schema_id": "ast2python.rc6.tests.v1",
            "source_root_hash": source_root_hash,
            "ok": True,
            "test_count": 226,
            "command": {"ok": True, "exit_code": 0},
        },
        "build": {
            "schema_id": "ast2python.rc6.build.v1",
            "source_root_hash": source_root_hash,
            "ok": True,
            "artifact_count": 1,
            "wheel_sha256": built_wheel_sha256,
            "command": {"ok": True, "exit_code": 0},
        },
        "clean_install": {
            "schema_id": "ast2python.rc6.clean_install.v1",
            "source_root_hash": source_root_hash,
            "ok": True,
            "import_check_count": 1,
            "wheel_sha256": built_wheel_sha256,
            "command": {"ok": True, "exit_code": 0},
        },
        "rc5_differential": {
            "schema_id": "ast2python.rc6.rc5_differential.v1",
            "source_root_hash": source_root_hash,
            "ok": True,
            "rc5_commit": "df6783345ab7105334596b3685206a28e7f7e33e",
            "rc5_wheel_sha256": "31ce44ac739acc70841ecd5914c59e7893188e94102a3fca3bea2e95fb66bc34",
            "regressions": 0,
            "case_count": 2,
            "evidence_sha256": "9" * 64,
        },
        "tooling": {
            "schema_id": "ast2python.rc6.tooling_inventory.v1",
            "source_root_hash": source_root_hash,
            "tools": [
                {"name": name, "available": True}
                for name in ("pytest", "coverage", "ruff", "black", "mypy", "setuptools", "wheel")
            ],
        },
        "exact_pinelib_target": {
            "schema_id": "ast2python.rc6.exact_pinelib_target.v1",
            "source_root_hash": source_root_hash,
            "ok": True,
            "release_acceptance": "EXACT_PINELIB_RC6_ACCEPTED",
            "target_manifest_hash": target_manifest_hash,
            "expected_target_manifest_hash": target_manifest_hash,
            "wheel_sha256": pinelib_wheel_sha256,
            "expected_wheel_sha256": pinelib_wheel_sha256,
            "commit": pinelib_commit,
            "expected_commit": pinelib_commit,
            "case_count": 1,
        },
        "hosted_ci": {
            "schema_id": "ast2python.rc6.hosted_ci.v1",
            "source_root_hash": source_root_hash,
            "source_commit": source_commit,
            "ok": True,
            "python_versions": ["3.11", "3.12", "3.13"],
            "quality_ok": True,
            "job_count": 3,
            "target_manifest_hash": target_manifest_hash,
            "pinelib_wheel_sha256": pinelib_wheel_sha256,
            "pinelib_commit": pinelib_commit,
        },
    }


def test_final_gate_distinguishes_local_and_external() -> None:
    complete = _base_gate_inputs()
    result = build_final_gate(**complete)
    assert result["overall_release_ready"] is True
    assert result["authorization"] == {"merge": False, "release": False, "deployment": False}
    incomplete = copy.deepcopy(complete)
    incomplete["rc5_differential"] = {"ok": False}
    result = build_final_gate(**incomplete)
    assert result["local_candidate_ready"] is True
    assert result["overall_release_ready"] is False
    assert result["verdict"] == "PASS_LOCAL_CANDIDATE_EXTERNAL_GATES_PENDING"


def test_final_gate_fails_local_gate() -> None:
    values = _base_gate_inputs()
    values["tests"] = {"ok": False}
    result = build_final_gate(**values)
    assert result["local_candidate_ready"] is False
    assert result["verdict"] == "REQUEST_CHANGES_LOCAL_GATES_FAILED"


def test_final_gate_rejects_unstructured_ok_dictionaries() -> None:
    arbitrary: dict[str, Any] = {
        "source_manifest": {"ok": True, "root_hash": "sha256:" + "1" * 64},
        "git_state": {"ok": True},
        "syntax_matrix": {"ok": True},
        "workflow_pins": {"ok": True},
        "tests": {"ok": True},
        "build": {"ok": True},
        "clean_install": {"ok": True},
        "rc5_differential": {"ok": True},
        "tooling": {"ok": True},
        "exact_pinelib_target": {"ok": True},
        "hosted_ci": {"ok": True},
    }

    result = build_final_gate(**arbitrary)

    assert result["local_candidate_ready"] is False
    assert result["overall_release_ready"] is False


@pytest.mark.parametrize(
    "evidence_name",
    [
        "git_state",
        "syntax_matrix",
        "workflow_pins",
        "tests",
        "build",
        "clean_install",
        "rc5_differential",
        "tooling",
        "exact_pinelib_target",
        "hosted_ci",
    ],
)
def test_final_gate_requires_exact_schema_and_source_binding(evidence_name: str) -> None:
    values = _base_gate_inputs()
    evidence = values[evidence_name]
    assert isinstance(evidence, dict)
    evidence["schema_id"] = "wrong.schema"
    evidence["source_root_hash"] = "sha256:" + "f" * 64

    assert build_final_gate(**values)["overall_release_ready"] is False


def test_final_gate_checks_commands_counts_and_rc5_regressions() -> None:
    values = _base_gate_inputs()
    values["tests"]["command"]["exit_code"] = 1
    values["tests"]["command"]["ok"] = False
    values["tests"]["test_count"] = 0
    values["rc5_differential"]["regressions"] = 1
    values["rc5_differential"]["case_count"] = 0

    result = build_final_gate(**values)

    assert result["local_candidate_ready"] is False
    assert result["external_gates"]["rc5_differential"] is False


def test_final_gate_requires_exact_hashes_and_hosted_source_identity() -> None:
    values = _base_gate_inputs()
    values["exact_pinelib_target"]["expected_target_manifest_hash"] = "sha256:" + "a" * 64
    values["exact_pinelib_target"]["expected_wheel_sha256"] = "b" * 64
    values["exact_pinelib_target"]["expected_commit"] = "c" * 40
    values["hosted_ci"]["source_commit"] = "d" * 40
    values["hosted_ci"]["python_versions"] = ["3.11", "3.12"]

    result = build_final_gate(**values)

    assert result["overall_release_ready"] is False
    assert result["external_gates"]["rc5_differential"] is True
    assert result["external_gates"]["exact_pinelib_target"] is False
    assert result["external_gates"]["hosted_python_3_11_3_12_3_13"] is False
    assert result["external_gates"]["hosted_ruff_black_mypy"] is False
