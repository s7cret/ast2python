"""OpenPine 5.0 generated artifact metadata."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from ast2python.version import __version__

GENERATED_ARTIFACT_V2 = "openpine.generated_artifact.v2"
DEFAULT_IMPORT_ALLOWLIST = (
    "pinelib",
    "pinelib.core",
    "pinelib.strategy",
    "pinelib.request",
    "pinelib.ta",
    "pinelib.math",
    "pinelib.color",
    "pinelib.string",
)


class GeneratedArtifactError(ValueError):
    code = "UNKNOWN_SEMANTIC_PROFILE"


def resolve_semantic_profile(value: str | None) -> str:
    if value is None:
        return "strict_5x"
    if value in {"strict_5x", "legacy_4x"}:
        return value
    raise GeneratedArtifactError(f"unknown semantic profile: {value}")


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def extract_import_allowlist(code: str) -> tuple[str, ...]:
    names: list[str] = []
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            names.append(stripped.split()[1].split(".", 1)[0])
        elif stripped.startswith("from "):
            parts = stripped.split()
            if len(parts) >= 2:
                names.append(parts[1])
    filtered = [name for name in names if name.startswith("pinelib")]
    return tuple(dict.fromkeys(filtered or DEFAULT_IMPORT_ALLOWLIST))


def build_generated_artifact_v2(
    *,
    code: str,
    source_map: Iterable[Mapping[str, Any]] | None = None,
    frontend_hash: str | None = None,
    semantic_profile: str | None = None,
    required_runtime_capabilities: Iterable[str] | None = None,
) -> dict[str, Any]:
    profile = resolve_semantic_profile(semantic_profile)
    source_map_json = list(source_map or [])
    return {
        "schema_id": GENERATED_ARTIFACT_V2,
        "schema_version": "2.0.0",
        "producer": "ast2python",
        "producer_version": __version__,
        "semantic_profile": profile,
        "source_hash": frontend_hash,
        "emitted_module_hash": _sha256_text(code),
        "source_map_hash": _sha256_text(repr(source_map_json)),
        "required_runtime_capabilities": list(required_runtime_capabilities or ("intent_tape",)),
        "import_allowlist": list(extract_import_allowlist(code)),
        "numeric_policy": "openpine.numeric.v1",
    }
