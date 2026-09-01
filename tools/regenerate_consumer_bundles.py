#!/usr/bin/env python3
"""Regenerate every coordinated bundle from canonical Pine2AST sources."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PINE2AST_ROOT = Path(
    "/home/moltbot1/.hermes/audits/cross-stack-rc6-local-fix-20260831/pine2ast/source"
)
_DATA_PREFIX = "pine2ast-stage6-corrected://pine2ast/hardening/data/"
_COORDINATED_SOURCES = {
    1: "historical_corpus/v1-self-bool-security.pine",
    2: "historical_corpus/v2-control-flow.pine",
    3: "historical_corpus/v3-security-default.pine",
    4: "historical_corpus/v4-arrays-var-compound.pine",
    5: "corpus/v5_minimal.pine",
    6: "corpus/v6_minimal.pine",
}


class RegenerationCase(NamedTuple):
    group: str
    source_path: Path
    source_name: str
    output_path: Path


def discover_regeneration_cases(
    repo_root: Path, pine2ast_root: Path
) -> tuple[RegenerationCase, ...]:
    data_root = pine2ast_root / "pine2ast" / "hardening" / "data"
    cases = [
        RegenerationCase(
            "coordinated",
            data_root / relative,
            Path(relative).name,
            repo_root / "tests" / "fixtures" / "consumer" / f"pine-v{version}-consumer-bundle.json",
        )
        for version, relative in sorted(_COORDINATED_SOURCES.items())
    ]
    manifest_path = repo_root / "tests" / "corpus" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest.get("cases")
    if manifest.get("schema_id") != "ast2python.stage4.normative_corpus.v1" or not isinstance(
        rows, list
    ):
        raise RuntimeError("unsupported normative corpus manifest")
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("normative corpus row must be an object")
        provenance = row.get("provenance")
        source_uri = provenance.get("source_path") if isinstance(provenance, dict) else None
        if not isinstance(source_uri, str) or not source_uri.startswith(_DATA_PREFIX):
            raise RuntimeError(f"{row.get('case_id')}: non-canonical Pine2AST source")
        output = row.get("consumer_bundle")
        if not isinstance(output, str):
            raise RuntimeError(f"{row.get('case_id')}: consumer bundle path is missing")
        source_name = row.get("source_name")
        if not isinstance(source_name, str) or not source_name:
            raise RuntimeError(f"{row.get('case_id')}: source name is missing")
        cases.append(
            RegenerationCase(
                "normative",
                data_root / source_uri.removeprefix(_DATA_PREFIX),
                source_name,
                repo_root / output,
            )
        )
    result = tuple(cases)
    if len(result) != 28 or len({case.output_path for case in result}) != len(result):
        raise RuntimeError("expected exactly 6 coordinated and 22 normative bundle outputs")
    missing = [str(case.source_path) for case in result if not case.source_path.is_file()]
    if missing:
        raise RuntimeError(f"canonical Pine2AST sources are missing: {missing}")
    return result


def _canonical_bundle_bytes(bundle: object) -> bytes:
    return (
        json.dumps(
            bundle,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def regenerate_cases(
    cases: Sequence[RegenerationCase],
    pine2ast_root: Path,
    *,
    check: bool,
) -> tuple[int, tuple[str, ...]]:
    pine2ast_path = str(pine2ast_root)
    inserted_path = pine2ast_path not in sys.path
    if inserted_path:
        sys.path.insert(0, pine2ast_path)
    try:
        from pine2ast.hardening import build_consumer_bundle

        stale: list[str] = []
        for case in cases:
            source = case.source_path.read_text(encoding="utf-8")
            expected = _canonical_bundle_bytes(
                build_consumer_bundle(source, source_name=case.source_name)
            )
            actual = case.output_path.read_bytes() if case.output_path.is_file() else None
            if actual == expected:
                continue
            stale.append(str(case.output_path))
            if not check:
                case.output_path.parent.mkdir(parents=True, exist_ok=True)
                case.output_path.write_bytes(expected)
        return (1 if check and stale else 0), tuple(stale)
    finally:
        if inserted_path:
            sys.path.remove(pine2ast_path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--pine2ast-root", type=Path, default=DEFAULT_PINE2AST_ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    pine2ast_root = args.pine2ast_root.resolve()
    code, stale = regenerate_cases(
        discover_regeneration_cases(repo_root, pine2ast_root),
        pine2ast_root,
        check=args.check,
    )
    action = "stale" if args.check else "regenerated"
    print(f"{len(stale)} {action} of 28 consumer bundles")
    if stale:
        print("\n".join(stale))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
