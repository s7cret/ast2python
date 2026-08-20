"""Catalog-valid openpine.generated_artifact.v2 envelopes."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any

from openpine_contracts import SemanticProfile, content_hash, validate_payload
from openpine_contracts.hashing import CONTENT_HASH_ALG, SERIALIZER_ID

from ast2python.contracts import GENERATED_ARTIFACT_CONTRACT
from ast2python.version import __version__

SCHEMA_VERSION = "2.0.0"
STACK_ID = "openpine-5.0"
LOWERING_VERSION = "ast2python.lowering.v1"
DEFAULT_IMPORT_ALLOWLIST = ("pinelib", "openpine_contracts")


def _producer_commit() -> str:
    return os.environ.get("OPENPINE_PRODUCER_COMMIT", "").strip() or "unknown"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _digest(payload: Mapping[str, Any] | str | bytes, schema_id: str) -> str:
    if isinstance(payload, bytes):
        text = payload.decode("utf-8")
    elif isinstance(payload, str):
        text = payload
    else:
        return content_hash(payload, schema_id=schema_id)
    from openpine_contracts.hashing import content_hash as _hash

    return _hash({"body": text}, schema_id=schema_id)


def resolve_compile_profile(value: object | None = None) -> SemanticProfile:
    if value is None:
        return SemanticProfile.STRICT_5X
    if isinstance(value, SemanticProfile):
        return value
    try:
        return SemanticProfile(str(value))
    except ValueError as exc:
        raise ValueError(f"PL_UNKNOWN_SEMANTIC_PROFILE: {value!r}") from exc


def build_generated_artifact_v2(
    *,
    source: str,
    ast_payload: Mapping[str, Any] | str,
    emitted_module: str,
    source_map: Mapping[str, Any] | str | list[Any],
    semantic_profile: object | None = None,
    required_runtime_capabilities: tuple[str, ...] = (),
    import_allowlist: tuple[str, ...] = DEFAULT_IMPORT_ALLOWLIST,
    producer_commit: str | None = None,
    created_at_utc_ms: int | None = None,
) -> dict[str, Any]:
    profile = resolve_compile_profile(semantic_profile)
    created = created_at_utc_ms if created_at_utc_ms is not None else _now_ms()
    commit = producer_commit or _producer_commit()
    payload: dict[str, Any] = {
        "schema_id": GENERATED_ARTIFACT_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "producer": "ast2python",
        "producer_version": __version__,
        "producer_commit": commit,
        "stack_id": STACK_ID,
        "created_at_utc_ms": created,
        "serializer_id": SERIALIZER_ID,
        "content_hash_alg": CONTENT_HASH_ALG,
        "source_hash": _digest(source, GENERATED_ARTIFACT_CONTRACT),
        "ast_hash": _digest(ast_payload, GENERATED_ARTIFACT_CONTRACT),
        "emitted_module_hash": _digest(emitted_module, GENERATED_ARTIFACT_CONTRACT),
        "source_map_hash": _digest(
            source_map if not isinstance(source_map, list) else {"entries": source_map},
            GENERATED_ARTIFACT_CONTRACT,
        ),
        "lowering_version": LOWERING_VERSION,
        "semantic_profile": profile.value,
        "required_runtime_capabilities": list(required_runtime_capabilities),
        "import_allowlist": list(import_allowlist),
    }
    unsigned = dict(payload)
    payload["content_hash"] = content_hash(unsigned, schema_id=GENERATED_ARTIFACT_CONTRACT)
    validate_payload(GENERATED_ARTIFACT_CONTRACT, payload)
    return payload
