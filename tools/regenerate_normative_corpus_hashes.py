#!/usr/bin/env python3
"""Deterministically regenerate normative identity-derived hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

IDENTITY_DERIVED_FIELDS = (
    "expected_ir_hash",
    "expected_emitted_module_hash",
    "expected_source_map_hash",
    "expected_artifact_hash",
)
PRODUCER_IDENTITY_FIELDS = (
    "consumer_bundle_hash",
    "catalog_hash",
    "required_operations",
    "required_capabilities",
)


def _expected_hashes(
    row: dict[str, Any],
    repo_root: Path,
    *,
    accept_producer_refresh: bool,
) -> dict[str, Any]:
    from ast2python.compiler import compile_reference_consumer_bundle as compile_consumer_bundle

    result = compile_consumer_bundle(
        repo_root / str(row["consumer_bundle"]),
        module_name=str(row["module_name"]),
    )
    producer_identity: dict[str, Any] = {
        "consumer_bundle_hash": result.plan.bundle_hash,
        "catalog_hash": result.plan.catalog_hash,
        "required_operations": sorted(result.plan.required_operations),
        "required_capabilities": sorted(result.plan.required_capabilities),
    }
    if not accept_producer_refresh:
        for field in PRODUCER_IDENTITY_FIELDS:
            if row.get(field) != producer_identity[field]:
                raise RuntimeError(
                    f"{row.get('case_id')}: {field} changed; "
                    "rerun with --accept-producer-refresh for a coordinated refresh"
                )
    derived_identity: dict[str, Any] = {
        "expected_ir_hash": result.plan.content_hash,
        "expected_emitted_module_hash": result.emitted.code_hash,
        "expected_source_map_hash": result.emitted.source_map.content_hash,
        "expected_artifact_hash": str(result.artifact.payload["content_hash"]),
    }
    if accept_producer_refresh:
        return {**producer_identity, **derived_identity}
    return derived_identity


def regenerate(
    manifest_path: Path,
    *,
    repo_root: Path,
    check: bool,
    accept_producer_refresh: bool = False,
) -> int:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if payload.get("schema_id") != "ast2python.stage4.normative_corpus.v1":
        raise RuntimeError("unsupported normative corpus schema")
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("normative corpus must contain cases")

    stale_case_ids: list[str] = []
    for raw in cases:
        if not isinstance(raw, dict):
            raise RuntimeError("normative corpus cases must be objects")
        expected = _expected_hashes(
            raw,
            repo_root,
            accept_producer_refresh=accept_producer_refresh,
        )
        expected_fields = (
            (*PRODUCER_IDENTITY_FIELDS, *IDENTITY_DERIVED_FIELDS)
            if accept_producer_refresh
            else IDENTITY_DERIVED_FIELDS
        )
        if any(raw.get(field) != expected[field] for field in expected_fields):
            stale_case_ids.append(str(raw.get("case_id")))
        if not check:
            raw.update(expected)

    if check and stale_case_ids:
        print(
            f"{len(stale_case_ids)} stale cases: {', '.join(stale_case_ids)}",
            file=sys.stderr,
        )
        return 1
    if not check:
        from ast2python.admission.canonical import canonical_json_bytes

        body = {key: value for key, value in payload.items() if key != "content_hash"}
        payload["content_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        print(f"{len(cases)} cases regenerated")
    else:
        print(f"{len(cases)} cases verified")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "tests" / "corpus" / "manifest.json",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--accept-producer-refresh", action="store_true")
    args = parser.parse_args(argv)
    return regenerate(
        args.manifest.resolve(),
        repo_root=args.repo_root.resolve(),
        check=args.check,
        accept_producer_refresh=args.accept_producer_refresh,
    )


if __name__ == "__main__":
    raise SystemExit(main())
