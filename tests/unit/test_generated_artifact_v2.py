from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openpine_contracts import (
    SemanticProfile,
    seal_content_hash,
    validate_payload,
)

import ast2python.artifact as artifact_module
from ast2python.artifact import _digest
from ast2python.ast.schema import load_ast
from ast2python.contracts import GENERATED_ARTIFACT_CONTRACT
from ast2python.translator import translate_ast

INDICATOR_FIXTURE = Path("tests/fixtures/pine2ast/current_basic_indicator.ast.json")
STRATEGY_FIXTURE = Path("tests/fixtures/ast/v0_2_strategy_loop.ast.json")
COMMITS = {
    "pine2ast": "4a3dd35b5b2d4385f09eed04b82804d689c080e8",
    "ast2python": "5b0cd4e6ea9bca2ee779a44882ddc321c628fed1",
    "pinelib": "801b908e0ba53d1387cfd032cb6d29aa53ba0ca0",
    "openpine-contracts": "af9ecbc455e9af83cdc609f6b6ff85c40fb6c8bb",
}


def _upstream_artifacts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    common = {
        "schema_version": "2.0.0",
        "producer": "test",
        "producer_version": "5.0.0-rc.4",
        "producer_commit": COMMITS["pine2ast"],
        "stack_id": "openpine-5.0",
        "created_at_utc_ms": 17,
        "serializer_id": "openpine.canonical.json.v1",
        "content_hash_alg": "sha256",
    }
    support = seal_content_hash(
        {
            **common,
            "schema_id": "openpine.support_profile.v2",
            "features": [
                {
                    "feature_id": "ta.sma",
                    "parse": "SUPPORTED",
                    "bind_type": "SUPPORTED",
                    "lower": "SUPPORTED",
                    "runtime": "SUPPORTED",
                    "data_mtf": "NOT_APPLICABLE",
                    "simulation": "SUPPORTED",
                    "live_safe": "SUPPORTED",
                    "visual": "NOT_APPLICABLE",
                    "numeric_parity": "SUPPORTED",
                    "capability_predicate": "runtime.ta.sma",
                }
            ],
        }
    )
    frontend = seal_content_hash(
        {
            **common,
            "schema_id": "openpine.frontend.v2",
            "declarations": {},
            "inputs": [],
            "referenced_builtins": ["ta.sma"],
            "request_usage": ["request.security"],
            "visual_requirements": ["plot"],
            "support_profile_ref": support["content_hash"],
            "semantic_profile": SemanticProfile.STRICT_5X.value,
        }
    )
    validate_payload("openpine.support_profile.v2", support)
    validate_payload("openpine.frontend.v2", frontend)
    ast_artifact = seal_content_hash(
        {
            **common,
            "schema_id": "pine.ast.v1",
            "schema_version": "1.0.0",
            "pine_version": "6",
            "nodes": [],
            "diagnostics": [],
        }
    )
    validate_payload("pine.ast.v1", ast_artifact)
    return frontend, support, ast_artifact


def _import_modules(code: str) -> list[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return sorted(modules)


def _runtime_and_strategy_call_lines(code: str) -> set[int]:
    tree = ast.parse(code)
    pinelib_names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith("pinelib"):
            continue
        pinelib_names.update(alias.asname or alias.name for alias in node.names)

    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        rendered = ast.unparse(node.func)
        if (
            rendered.startswith(("self.rt.", "self.ctx.", "runtime.", "strategy."))
            or isinstance(node.func, ast.Name)
            and node.func.id in pinelib_names
        ):
            lines.add(node.lineno)
    return lines


def _identity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    identity = dict(payload)
    identity.pop("content_hash")
    identity.pop("created_at_utc_ms")
    return identity


def test_canonical_translation_returns_catalog_valid_sealed_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frontend, support, ast_artifact = _upstream_artifacts()
    program = load_ast(INDICATOR_FIXTURE)
    source = '//@version=6\nindicator("My Indicator", overlay=true)\nplot(close)\n'

    monkeypatch.delenv("OPENPINE_PRODUCER_COMMITS_JSON", raising=False)
    with pytest.raises(ValueError, match="producer_commits"):
        translate_ast(
            program,
            source=source,
            frontend_artifact=frontend,
            support_profile=support,
            ast_artifact=ast_artifact,
        )
    result = translate_ast(
        program,
        source=source,
        frontend_artifact=frontend,
        support_profile=support,
        ast_artifact=ast_artifact,
        producer_commits=COMMITS,
        module_name="canonical.indicator",
        created_at_utc_ms=123,
    )
    artifact = result.generated_artifact

    validate_payload(GENERATED_ARTIFACT_CONTRACT, artifact)
    assert artifact["producer_version"] == "5.0.0-rc.4"
    assert artifact["producer_commit"] == COMMITS["ast2python"]
    assert artifact["producer_commits"] == COMMITS
    assert all(re.fullmatch(r"[0-9a-f]{40}", value) for value in COMMITS.values())
    assert "unknown" not in artifact["producer_commits"].values()
    assert artifact["frontend_artifact_hash"] == frontend["content_hash"]
    assert artifact["support_profile_hash"] == support["content_hash"]
    assert artifact["source_hash"] == _digest(source, GENERATED_ARTIFACT_CONTRACT)
    assert artifact["ast_hash"] == ast_artifact["content_hash"]
    assert artifact["emitted_module_hash"] == _digest(result.code, GENERATED_ARTIFACT_CONTRACT)
    assert artifact["source_map_hash"] == _digest(
        {"entries": result.source_map}, GENERATED_ARTIFACT_CONTRACT
    )
    assert artifact["import_allowlist"] == _import_modules(result.code)
    assert artifact["entrypoint_module"] == "canonical.indicator"
    assert artifact["entrypoint_class"] == "GeneratedIndicator"
    assert {"ta.sma", "request.security", "plot", "runtime.ta.sma"} <= set(
        artifact["required_runtime_capabilities"]
    )
    assert any(
        item.startswith(("runtime.", "pinelib."))
        for item in artifact["required_runtime_capabilities"]
    )


def test_created_at_does_not_change_content_identity_or_emitted_bytes() -> None:
    frontend, support, ast_artifact = _upstream_artifacts()
    program = load_ast(INDICATOR_FIXTURE)
    kwargs = {
        "source": "same source\n",
        "frontend_artifact": frontend,
        "support_profile": support,
        "ast_artifact": ast_artifact,
        "producer_commits": COMMITS,
        "module_name": "stable_indicator",
        "semantic_profile": SemanticProfile.STRICT_5X,
    }

    first = translate_ast(program, created_at_utc_ms=1, **kwargs)
    second = translate_ast(program, created_at_utc_ms=999, **kwargs)

    assert first.code.encode() == second.code.encode()
    assert json.dumps(first.source_map, sort_keys=True, separators=(",", ":")) == json.dumps(
        second.source_map, sort_keys=True, separators=(",", ":")
    )
    assert first.generated_artifact["content_hash"] == second.generated_artifact["content_hash"]
    assert _identity_payload(first.generated_artifact) == _identity_payload(
        second.generated_artifact
    )
    assert (
        first.generated_artifact["created_at_utc_ms"]
        != second.generated_artifact["created_at_utc_ms"]
    )


def test_source_map_covers_every_emitted_runtime_and_strategy_call() -> None:
    result = translate_ast(
        load_ast(STRATEGY_FIXTURE),
        source="strategy fixture\n",
        module_name="mapped_strategy",
        producer_commits=COMMITS,
    )

    required_lines = _runtime_and_strategy_call_lines(result.code)
    mapped = {entry["python_line"]: entry for entry in result.source_map}
    assert required_lines
    assert required_lines <= set(mapped)
    assert all(
        mapped[line].get("pine_line") is not None
        or mapped[line].get("origin") == "generated_runtime_scaffold"
        for line in required_lines
    )
    assert result.generated_artifact["entrypoint_class"] == "GeneratedStrategy"


def test_production_commits_are_explicit_and_not_environment_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENPINE_PRODUCER_COMMIT", "unknown")
    frontend, support, ast_artifact = _upstream_artifacts()

    result = translate_ast(
        load_ast(INDICATOR_FIXTURE),
        source="fixture\n",
        module_name="sealed_commits",
        frontend_artifact=frontend,
        support_profile=support,
        ast_artifact=ast_artifact,
        producer_commits=COMMITS,
    )

    assert result.generated_artifact["producer_commit"] == COMMITS["ast2python"]
    assert result.generated_artifact["producer_commits"] == COMMITS


def test_write_to_persists_the_generated_artifact_envelope(tmp_path: Path) -> None:
    result = translate_ast(
        load_ast(INDICATOR_FIXTURE),
        source="fixture\n",
        module_name="persisted_artifact",
        producer_commits=COMMITS,
    )

    paths = result.write_to(tmp_path)

    assert paths["generated_artifact"].name == "persisted_artifact.artifact.json"
    persisted = json.loads(paths["generated_artifact"].read_text(encoding="utf-8"))
    assert persisted == result.generated_artifact
    validate_payload(GENERATED_ARTIFACT_CONTRACT, persisted)


def test_canonical_translation_rejects_tampered_upstream_seal() -> None:
    frontend, support, ast_artifact = _upstream_artifacts()
    support["features"] = []

    with pytest.raises(ValueError, match="support profile"):
        translate_ast(
            load_ast(INDICATOR_FIXTURE),
            source="fixture\n",
            frontend_artifact=frontend,
            support_profile=support,
            ast_artifact=ast_artifact,
            producer_commits=COMMITS,
        )


def test_artifact_capability_and_reference_defensive_paths() -> None:
    code = """import os
import pinelib as pine
from pinelib.ta import sma as runtime_sma

runtime.foo()
strategy.bar()
pine.helper()
runtime_sma()
"""
    assert artifact_module.import_allowlist_from_module(code) == (
        "os",
        "pinelib",
        "pinelib.ta",
    )
    capabilities = artifact_module.required_runtime_capabilities_from_inputs(
        code,
        support_profile={"features": ["invalid", {"capability_predicate": "declared.capability"}]},
    )
    assert {
        "runtime.foo",
        "strategy.bar",
        "pinelib.helper",
        "pinelib.ta.sma",
        "declared.capability",
    } <= set(capabilities)

    digest = "sha256:" + "a" * 64
    assert artifact_module._reference_hash(digest, schema_id="openpine.frontend.v2") == digest
    assert artifact_module._reference_hash("plain", schema_id="openpine.frontend.v2") != digest
    frontend, _, _ = _upstream_artifacts()
    assert (
        artifact_module._reference_hash(frontend, schema_id="openpine.frontend.v2")
        == frontend["content_hash"]
    )
    invalid = dict(frontend, content_hash="sha256:" + "0" * 64)
    assert (
        artifact_module._reference_hash(invalid, schema_id="openpine.frontend.v2")
        != invalid["content_hash"]
    )
    with pytest.raises(ValueError, match="not schema-valid"):
        artifact_module._verified_reference_hash(
            {}, schema_id="openpine.frontend.v2", label="frontend artifact"
        )


def test_producer_commit_resolution_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="contain exactly"):
        artifact_module.resolve_producer_commits({}, canonical_required=False)
    malformed = dict(COMMITS, pinelib="unknown")
    with pytest.raises(ValueError, match="exact 40-character"):
        artifact_module.resolve_producer_commits(malformed, canonical_required=False)

    monkeypatch.setenv("OPENPINE_PRODUCER_COMMITS_JSON", "{")
    with pytest.raises(ValueError, match="invalid JSON"):
        artifact_module.resolve_producer_commits(None, canonical_required=False)
    monkeypatch.setenv("OPENPINE_PRODUCER_COMMITS_JSON", "[]")
    with pytest.raises(ValueError, match="must be an object"):
        artifact_module.resolve_producer_commits(None, canonical_required=False)
    monkeypatch.setenv("OPENPINE_PRODUCER_COMMITS_JSON", json.dumps(COMMITS))
    assert artifact_module.resolve_producer_commits(None, canonical_required=False) == COMMITS
    monkeypatch.delenv("OPENPINE_PRODUCER_COMMITS_JSON", raising=False)
    monkeypatch.setattr(artifact_module, "_development_producer_commits", lambda: COMMITS)
    assert artifact_module.resolve_producer_commits(None, canonical_required=False) == COMMITS


def test_development_git_identity_and_entrypoint_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_oserror(*_args: object, **_kwargs: object) -> None:
        raise OSError("git unavailable")

    monkeypatch.setattr(artifact_module.subprocess, "run", raise_oserror)
    with pytest.raises(ValueError, match="cannot resolve"):
        artifact_module._git_head(Path("/tmp"))
    monkeypatch.setattr(
        artifact_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="invalid\n"),
    )
    with pytest.raises(ValueError, match="invalid development"):
        artifact_module._git_head(Path("/tmp"))
    monkeypatch.setattr(
        artifact_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=COMMITS["ast2python"] + "\n"),
    )
    assert artifact_module._git_head(Path("/tmp")) == COMMITS["ast2python"]

    repo = Path(artifact_module.__file__).resolve().parents[1]
    workspace = repo.parent
    paths = {
        "pine2ast": workspace / "pine2ast",
        "ast2python": repo,
        "pinelib": workspace / "pinelib",
        "openpine-contracts": workspace / "openpine-contracts",
    }
    monkeypatch.setattr(
        artifact_module,
        "_git_head",
        lambda path: next(COMMITS[key] for key, value in paths.items() if value == path),
    )
    assert artifact_module._development_producer_commits() == COMMITS

    with pytest.raises(ValueError, match="exactly one"):
        artifact_module._entrypoint_class("class Other:\n    pass\n", None)
    with pytest.raises(ValueError, match="does not match"):
        artifact_module._entrypoint_class(
            "class GeneratedIndicator:\n    pass\n", "GeneratedStrategy"
        )


def test_canonical_bundle_and_created_time_errors() -> None:
    frontend, support, ast_artifact = _upstream_artifacts()
    emitted = "class GeneratedIndicator:\n    pass\n"
    common = {
        "ast_payload": {},
        "emitted_module": emitted,
        "source_map": [],
        "producer_commits": COMMITS,
    }
    with pytest.raises(ValueError, match="nonnegative integer"):
        artifact_module.build_generated_artifact_v2(
            source="fixture\n", created_at_utc_ms=True, **common
        )
    with pytest.raises(ValueError, match="source is required"):
        artifact_module.build_generated_artifact_v2(
            source="",
            frontend_artifact=frontend,
            support_profile=support,
            ast_artifact=ast_artifact,
            **common,
        )
    with pytest.raises(ValueError, match="requires frontend artifact"):
        artifact_module.build_generated_artifact_v2(
            source="fixture\n", frontend_artifact=frontend, **common
        )

    invalid_support = dict(support)
    invalid_support.pop("features")
    invalid_support = seal_content_hash(invalid_support)
    with pytest.raises(ValueError, match="support profile is not schema-valid"):
        artifact_module.build_generated_artifact_v2(
            source="fixture\n",
            frontend_artifact=frontend,
            support_profile=invalid_support,
            ast_artifact=ast_artifact,
            **common,
        )

    mismatched_frontend = dict(frontend, support_profile_ref="sha256:" + "0" * 64)
    mismatched_frontend = seal_content_hash(mismatched_frontend)
    with pytest.raises(ValueError, match="does not match support profile"):
        artifact_module.build_generated_artifact_v2(
            source="fixture\n",
            frontend_artifact=mismatched_frontend,
            support_profile=support,
            ast_artifact=ast_artifact,
            **common,
        )
