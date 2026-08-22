"""Catalog-valid, deterministic ``openpine.generated_artifact.v2`` envelopes."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from openpine_contracts import (
    SemanticProfile,
    content_hash,
    seal_content_hash,
    validate_payload,
    verify_content_hash,
)
from openpine_contracts.hashing import CONTENT_HASH_ALG, SERIALIZER_ID

from ast2python.contracts import GENERATED_ARTIFACT_CONTRACT
from ast2python.naming import snake_case
from ast2python.version import __version__

SCHEMA_VERSION = "2.0.0"
STACK_ID = "openpine-5.0"
LOWERING_VERSION = "ast2python.lowering.v2"
FRONTEND_CONTRACT = "openpine.frontend.v2"
SUPPORT_PROFILE_CONTRACT = "openpine.support_profile.v2"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PRODUCER_COMPONENTS = ("pine2ast", "ast2python", "pinelib", "openpine-contracts")


def _artifact_semver(version: str) -> str:
    """Render the coordinated PEP 440 RC as the schema's SemVer spelling."""

    match = re.fullmatch(r"(\d+\.\d+\.\d+)rc(\d+)", version)
    return f"{match.group(1)}-rc.{match.group(2)}" if match else version


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(
    payload: Mapping[str, Any] | Sequence[Any] | str | bytes,
    schema_id: str,
) -> str:
    """Hash bytes/text or a deterministic JSON representation in a schema domain."""

    if isinstance(payload, bytes):
        body = payload.decode("utf-8")
    elif isinstance(payload, str):
        body = payload
    else:
        body = _stable_json(payload)
    return content_hash({"body": body}, schema_id=schema_id)


def resolve_compile_profile(value: object | None = None) -> SemanticProfile:
    if value is None:
        return SemanticProfile.STRICT_5X
    if isinstance(value, SemanticProfile):
        return value
    try:
        return SemanticProfile(str(value))
    except ValueError as exc:
        raise ValueError(f"PL_UNKNOWN_SEMANTIC_PROFILE: {value!r}") from exc


def import_allowlist_from_module(emitted_module: str) -> tuple[str, ...]:
    """Derive the import boundary from emitted Python, never caller input."""

    modules: set[str] = set()
    for node in ast.walk(ast.parse(emitted_module)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return tuple(sorted(modules))


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _lowering_capabilities(emitted_module: str) -> set[str]:
    tree = ast.parse(emitted_module)
    imported_runtime_names: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("pinelib"):
            for alias in node.names:
                imported_runtime_names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("pinelib"):
                    imported_runtime_names[alias.asname or alias.name] = alias.name

    capabilities: set[str] = set()
    for candidate in ast.walk(tree):
        if not isinstance(candidate, ast.Call):
            continue
        name = _dotted_name(candidate.func)
        if name is None:
            continue
        if name.startswith("self.rt."):
            capabilities.add(f"runtime.{name.removeprefix('self.rt.')}")
        elif name.startswith("self.ctx."):
            capabilities.add(f"strategy.{name.removeprefix('self.ctx.')}")
        elif name.startswith("runtime.") or name.startswith("strategy."):
            capabilities.add(name)
        else:
            root = name.split(".", 1)[0]
            imported = imported_runtime_names.get(root)
            if imported is not None:
                suffix = name.removeprefix(root)
                capabilities.add(f"{imported}{suffix}")
    return capabilities


def required_runtime_capabilities_from_inputs(
    emitted_module: str,
    *,
    frontend_artifact: Mapping[str, Any] | None = None,
    support_profile: Mapping[str, Any] | None = None,
    additional: Sequence[str] = (),
) -> tuple[str, ...]:
    """Compute capabilities as a union of frontend, support, and lowering evidence."""

    capabilities = _lowering_capabilities(emitted_module)
    if frontend_artifact is not None:
        for field in ("referenced_builtins", "request_usage", "visual_requirements"):
            values = frontend_artifact.get(field, ())
            if isinstance(values, list):
                capabilities.update(item for item in values if isinstance(item, str) and item)
    if support_profile is not None:
        features = support_profile.get("features", ())
        if isinstance(features, list):
            for feature in features:
                if not isinstance(feature, Mapping):
                    continue
                predicate = feature.get("capability_predicate")
                if isinstance(predicate, str) and predicate:
                    capabilities.add(predicate)
    capabilities.update(item for item in additional if isinstance(item, str) and item)
    return tuple(sorted(capabilities))


def complete_source_map(
    emitted_module: str, source_map: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Ensure every emitted Python call has a deterministic source-map entry."""

    completed = [dict(entry) for entry in source_map]
    mapped_lines = {
        entry.get("python_line") for entry in completed if type(entry.get("python_line")) is int
    }
    call_lines = sorted(
        {node.lineno for node in ast.walk(ast.parse(emitted_module)) if isinstance(node, ast.Call)}
    )
    for line in call_lines:
        if line in mapped_lines:
            continue
        completed.append(
            {
                "python_line": line,
                "pine_line": None,
                "pine_column": None,
                "pine_end_line": None,
                "pine_end_column": None,
                "pine_source": None,
                "origin": "generated_runtime_scaffold",
            }
        )
    return sorted(completed, key=lambda entry: int(entry["python_line"]))


def _reference_hash(value: Mapping[str, Any] | str | None, *, schema_id: str) -> str:
    if isinstance(value, str):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            return value
        return _digest(value, schema_id)
    if value is None:
        return _digest({}, schema_id)
    stored = value.get("content_hash")
    if isinstance(stored, str) and verify_content_hash(value, schema_id=schema_id):
        return stored
    return _digest(value, schema_id)


def _verified_reference_hash(value: Mapping[str, Any], *, schema_id: str, label: str) -> str:
    try:
        validate_payload(schema_id, value)
    except Exception as exc:
        raise ValueError(f"{label} is not schema-valid") from exc
    if not verify_content_hash(value, schema_id=schema_id):
        raise ValueError(f"{label} content hash is invalid")
    stored = value.get("content_hash")
    assert isinstance(stored, str)
    return stored


def _validate_producer_commits(value: Mapping[str, Any]) -> dict[str, str]:
    if set(value) != set(PRODUCER_COMPONENTS):
        raise ValueError("producer_commits must contain exactly " + ", ".join(PRODUCER_COMPONENTS))
    commits = {component: value[component] for component in PRODUCER_COMPONENTS}
    if not all(
        isinstance(commit, str) and COMMIT_RE.fullmatch(commit) for commit in commits.values()
    ):
        raise ValueError("producer_commits values must be exact 40-character lowercase Git SHAs")
    return {component: str(commit) for component, commit in commits.items()}


def _git_head(path: Path) -> str:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"cannot resolve development Git identity for {path}") from exc
    if not COMMIT_RE.fullmatch(commit):
        raise ValueError(f"invalid development Git identity for {path}")
    return commit


def _development_producer_commits() -> dict[str, str]:
    repo = Path(__file__).resolve().parents[1]
    workspace = repo.parent
    paths = {
        "pine2ast": workspace / "pine2ast",
        "ast2python": repo,
        "pinelib": workspace / "pinelib",
        "openpine-contracts": workspace / "openpine-contracts",
    }
    return {component: _git_head(path) for component, path in paths.items()}


def resolve_producer_commits(
    value: Mapping[str, Any] | None,
    *,
    canonical_required: bool,
) -> dict[str, str]:
    if value is not None:
        return _validate_producer_commits(value)
    raw = os.environ.get("OPENPINE_PRODUCER_COMMITS_JSON", "").strip()
    if raw:
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("OPENPINE_PRODUCER_COMMITS_JSON is invalid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise ValueError("OPENPINE_PRODUCER_COMMITS_JSON must be an object")
        return _validate_producer_commits(decoded)
    if canonical_required:
        raise ValueError("producer_commits are required for canonical production translation")
    return _development_producer_commits()


def _entrypoint_class(emitted_module: str, declared: str | None) -> str:
    generated = [
        node.name
        for node in ast.parse(emitted_module).body
        if isinstance(node, ast.ClassDef) and node.name.startswith("Generated")
    ]
    if len(generated) != 1:
        raise ValueError("emitted module must declare exactly one Generated* entrypoint class")
    if declared is not None and declared != generated[0]:
        raise ValueError(
            f"declared entrypoint class {declared!r} does not match emitted {generated[0]!r}"
        )
    return generated[0]


def _entrypoint_module(value: str) -> str:
    return ".".join(snake_case(part) for part in value.split("."))


def build_generated_artifact_v2(
    *,
    source: str,
    ast_payload: Mapping[str, Any] | str,
    emitted_module: str,
    source_map: Mapping[str, Any] | str | list[Any],
    ast_artifact: Mapping[str, Any] | None = None,
    frontend_artifact: Mapping[str, Any] | str | None = None,
    support_profile: Mapping[str, Any] | str | None = None,
    producer_commits: Mapping[str, Any] | None = None,
    semantic_profile: object | None = None,
    required_runtime_capabilities: tuple[str, ...] = (),
    entrypoint_module: str = "generated",
    entrypoint_class: str | None = None,
    created_at_utc_ms: int = 0,
) -> dict[str, Any]:
    profile = resolve_compile_profile(semantic_profile)
    if type(created_at_utc_ms) is not int or created_at_utc_ms < 0:
        raise ValueError("created_at_utc_ms must be a nonnegative integer")

    frontend_mapping = frontend_artifact if isinstance(frontend_artifact, Mapping) else None
    support_mapping = support_profile if isinstance(support_profile, Mapping) else None
    canonical_inputs = any(
        (isinstance(value, Mapping) and value.get("schema_id") == schema_id)
        for value, schema_id in (
            (frontend_artifact, FRONTEND_CONTRACT),
            (support_profile, SUPPORT_PROFILE_CONTRACT),
            (ast_artifact, "pine.ast.v1"),
        )
    )
    commits = resolve_producer_commits(
        producer_commits,
        canonical_required=canonical_inputs,
    )
    if canonical_inputs:
        if not source:
            raise ValueError("source is required for canonical production translation")
        if frontend_mapping is None or support_mapping is None or ast_artifact is None:
            raise ValueError(
                "canonical translation requires frontend artifact, support profile, and AST artifact"
            )
        frontend_hash = _verified_reference_hash(
            frontend_mapping,
            schema_id=FRONTEND_CONTRACT,
            label="frontend artifact",
        )
        support_hash = _verified_reference_hash(
            support_mapping,
            schema_id=SUPPORT_PROFILE_CONTRACT,
            label="support profile",
        )
        ast_hash = _verified_reference_hash(
            ast_artifact,
            schema_id="pine.ast.v1",
            label="AST artifact",
        )
        if frontend_mapping.get("support_profile_ref") != support_hash:
            raise ValueError("frontend artifact support_profile_ref does not match support profile")
    else:
        frontend_hash = _reference_hash(frontend_artifact, schema_id=FRONTEND_CONTRACT)
        support_hash = _reference_hash(support_profile, schema_id=SUPPORT_PROFILE_CONTRACT)
        ast_hash = _digest(ast_payload, GENERATED_ARTIFACT_CONTRACT)

    source_map_payload: Mapping[str, Any] | str = (
        {"entries": source_map} if isinstance(source_map, list) else source_map
    )
    payload: dict[str, Any] = {
        "schema_id": GENERATED_ARTIFACT_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "producer": "ast2python",
        "producer_version": _artifact_semver(__version__),
        "producer_commit": commits["ast2python"],
        "stack_id": STACK_ID,
        "created_at_utc_ms": created_at_utc_ms,
        "serializer_id": SERIALIZER_ID,
        "content_hash_alg": CONTENT_HASH_ALG,
        "source_hash": _digest(source, GENERATED_ARTIFACT_CONTRACT),
        "frontend_artifact_hash": frontend_hash,
        "ast_hash": ast_hash,
        "emitted_module_hash": _digest(emitted_module, GENERATED_ARTIFACT_CONTRACT),
        "source_map_hash": _digest(source_map_payload, GENERATED_ARTIFACT_CONTRACT),
        "support_profile_hash": support_hash,
        "lowering_version": LOWERING_VERSION,
        "producer_commits": commits,
        "semantic_profile": profile.value,
        "required_runtime_capabilities": list(
            required_runtime_capabilities_from_inputs(
                emitted_module,
                frontend_artifact=frontend_mapping,
                support_profile=support_mapping,
                additional=required_runtime_capabilities,
            )
        ),
        "import_allowlist": list(import_allowlist_from_module(emitted_module)),
        "entrypoint_module": _entrypoint_module(entrypoint_module),
        "entrypoint_class": _entrypoint_class(emitted_module, entrypoint_class),
    }
    sealed = seal_content_hash(payload, schema_id=GENERATED_ARTIFACT_CONTRACT)
    validate_payload(GENERATED_ARTIFACT_CONTRACT, sealed)
    return sealed


__all__ = [
    "PRODUCER_COMPONENTS",
    "build_generated_artifact_v2",
    "complete_source_map",
    "import_allowlist_from_module",
    "required_runtime_capabilities_from_inputs",
    "resolve_compile_profile",
    "resolve_producer_commits",
]
