#!/usr/bin/env python3
"""Regenerate the compiler-reference direct ABI bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _python_name(prefix: str, identity: str) -> str:
    return f"{prefix}_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"


def _operation_name(operation_id: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9_]+", "_", operation_id).strip("_")
    return f"op_{suffix}"


def regenerate(target_path: Path, corpus_path: Path) -> None:
    target = json.loads(target_path.read_text(encoding="utf-8"))
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))

    for operation in target["operations"]:
        operation["python_name"] = _operation_name(operation["name"])

    call_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    value_symbols: set[str] = set()
    bundle_specs = [
        (REPO_ROOT / case["consumer_bundle"], int(case["pine_version"])) for case in corpus["cases"]
    ]
    for fixture in sorted(
        (REPO_ROOT / "tests" / "fixtures" / "consumer").glob("pine-v*-consumer-bundle.json")
    ):
        fixture_payload = json.loads(fixture.read_text(encoding="utf-8"))
        bundle_specs.append((fixture, int(fixture_payload["version_context"]["pine_version"])))
    for bundle_path, version in bundle_specs:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        for call in bundle["semantic_facts"]["calls"]:
            symbol_id = str(call["symbol_id"])
            if symbol_id.startswith("user:function:"):
                continue
            key = (symbol_id, str(call["overload_id"]), str(call["call_form"]))
            parameters = [
                str(argument["parameter_name"])
                for argument in sorted(call["arguments"], key=lambda row: row["parameter_index"])
            ]
            existing = call_rows.get(key)
            if existing is None:
                existing = {
                    "symbol_id": key[0],
                    "overload_id": key[1],
                    "call_form": key[2],
                    "python_name": _python_name("call", "|".join(key)),
                    "parameters": parameters,
                    "return_type": str(call["return_type"]),
                    "state_model": "STATEFUL" if call["stateful"] else "PURE",
                    "supported_pine_versions": [],
                }
                call_rows[key] = existing
            elif existing["parameters"] != parameters:
                shorter, longer = sorted((existing["parameters"], parameters), key=len)
                if longer[: len(shorter)] != shorter:
                    raise RuntimeError(f"inconsistent parameter order for {key!r}")
                existing["parameters"] = longer
            existing["supported_pine_versions"].append(version)

        for fact in bundle["semantic_facts"]["facts"]:
            symbol_id = fact.get("symbol_id")
            resolved_type = fact.get("resolved_type") or {}
            if (
                isinstance(symbol_id, str)
                and symbol_id.startswith("pine:")
                and fact.get("node_kind") in {"Identifier", "MemberAccessExpr"}
                and resolved_type.get("base") != "namespace"
            ):
                value_symbols.add(symbol_id)

    for row in call_rows.values():
        row["supported_pine_versions"] = sorted(set(row["supported_pine_versions"]))
    target["call_bindings"] = [call_rows[key] for key in sorted(call_rows)]
    target["value_bindings"] = [
        {"symbol_id": symbol_id, "python_name": _python_name("value", symbol_id)}
        for symbol_id in sorted(value_symbols)
    ]
    target.pop("content_hash", None)
    encoded = json.dumps(
        target,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    target["content_hash"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    target_path.write_text(
        json.dumps(target, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        type=Path,
        default=REPO_ROOT / "ast2python" / "target_data" / "reference_target_v1.json",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=REPO_ROOT / "tests" / "corpus" / "manifest.json",
    )
    args = parser.parse_args()
    regenerate(args.target.resolve(), args.corpus.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
