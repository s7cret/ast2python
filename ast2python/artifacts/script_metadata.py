"""Read metadata only after verifying the generated module and its envelope."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def admitted_script_metadata(
    namespace: Mapping[str, Any], envelope: Mapping[str, Any]
) -> dict[str, Any]:
    metadata = namespace.get("SCRIPT_METADATA")
    if metadata is None:
        # Older native modules had no input support. Never infer descriptors
        # from titles or patch the source of those artifacts.
        return {"inputs": {}, "declaration": {}}
    if not isinstance(metadata, Mapping) or set(metadata) != {
        "schema_id",
        "pine_version",
        "source_hash",
        "declaration",
        "inputs",
    }:
        raise ValueError("generated script metadata is malformed")
    version = envelope.get("version_context", {}).get("pine_version")
    if (
        metadata["schema_id"] != "ast2python.script_metadata.v1"
        or metadata["pine_version"] != version
        or metadata["source_hash"] != envelope["source_hash"]
    ):
        raise ValueError("generated script metadata differs from artifact identity")
    if not isinstance(metadata["declaration"], Mapping) or not isinstance(
        metadata["inputs"], Mapping
    ):
        raise ValueError("generated declaration and input descriptors must be objects")
    return deepcopy(dict(metadata))
