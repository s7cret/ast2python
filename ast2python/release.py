from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from ast2python.distribution import distribution_manifest
from ast2python.quality import architecture_report, duplicate_report
from ast2python.version import __version__

REQUIRED_DOCS = (
    "docs/README.md",
    "docs/ARCHITECTURE.md",
    "docs/COMPATIBILITY.md",
    "docs/DEVELOPMENT.md",
    "docs/OPENPINE_PIPELINE.md",
    "docs/RELEASE_4_0.md",
    "docs/SECURITY.md",
)


REQUIRED_CROSS_LAYER_CASES = 20
REQUIRED_CROSS_LAYER_LAYERS = {"parse", "semantic", "codegen", "runtime", "backtest"}
CROSS_LAYER_CATALOG_SCHEMA = "ast2python.cross_layer_catalog.v1"
CANONICAL_CORPUS_SCHEMA = "ast2python.canonical_corpus.v1"


@dataclass(frozen=True)
class ReleaseReport:
    version: str
    ok: bool
    docs_ok: bool
    missing_docs: tuple[str, ...]
    architecture_ok: bool
    duplicate_ok: bool
    distribution_ok: bool
    cross_layer_catalog_ok: bool
    cross_layer_case_count: int
    manifest_file: str


def _catalog_relative_path(root_path: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None
    candidate = (root_path / value).resolve()
    try:
        candidate.relative_to(root_path.resolve())
    except ValueError:
        return None
    return candidate


def _cross_layer_catalog_status(root_path: Path) -> tuple[bool, int]:
    catalog_path = root_path / "ast2python/lowering_matrix/cross_layer_catalog.json"
    if not catalog_path.exists():
        return False, 0
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(catalog, dict):
            return False, 0
        case_count = catalog["case_count"]
        minimum = catalog["minimum_case_count"]
        if type(case_count) is not int or type(minimum) is not int:
            return False, 0
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return False, 0

    evidence = catalog.get("evidence")
    manifest_path = _catalog_relative_path(root_path, catalog.get("source_manifest"))
    evidence_test_path = _catalog_relative_path(root_path, catalog.get("evidence_test"))
    if (
        catalog.get("schema_version") != CROSS_LAYER_CATALOG_SCHEMA
        or minimum < REQUIRED_CROSS_LAYER_CASES
        or case_count < REQUIRED_CROSS_LAYER_CASES
        or not isinstance(evidence, list)
        or len(evidence) != case_count
        or manifest_path is None
        or evidence_test_path is None
        or not manifest_path.is_file()
        or not evidence_test_path.is_file()
    ):
        return False, case_count

    evidence_ids: list[str] = []
    for item in evidence:
        if not isinstance(item, dict):
            return False, case_count
        case_id = item.get("case_id")
        layers = item.get("layers")
        if (
            not isinstance(case_id, str)
            or not case_id
            or item.get("status") != "DONE_VERIFIED"
            or not isinstance(layers, list)
            or any(not isinstance(layer, str) for layer in layers)
            or not REQUIRED_CROSS_LAYER_LAYERS.issubset(set(layers))
        ):
            return False, case_count
        evidence_ids.append(case_id)
    if len(set(evidence_ids)) != case_count:
        return False, case_count

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return False, case_count
        manifest_minimum = manifest["minimum_case_count"]
        if type(manifest_minimum) is not int:
            return False, case_count
        cases = manifest["cases"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return False, case_count
    if (
        manifest.get("schema_version") != CANONICAL_CORPUS_SCHEMA
        or manifest_minimum < REQUIRED_CROSS_LAYER_CASES
        or not isinstance(cases, list)
        or len(cases) != case_count
    ):
        return False, case_count
    manifest_ids = [item.get("id") for item in cases if isinstance(item, dict)]
    if (
        len(manifest_ids) != case_count
        or any(not isinstance(case_id, str) or not case_id for case_id in manifest_ids)
        or len(set(manifest_ids)) != case_count
        or evidence_ids != manifest_ids
        or minimum != manifest_minimum
    ):
        return False, case_count
    for manifest_case, evidence_item in zip(cases, evidence, strict=True):
        manifest_case = cast(dict[str, object], manifest_case)
        features = manifest_case.get("features")
        if (
            not isinstance(features, list)
            or any(not isinstance(feature, str) or not feature for feature in features)
            or len(set(features)) != len(features)
            or evidence_item
            != {
                "case_id": manifest_case["id"],
                "features": sorted(features),
                "layers": ["parse", "semantic", "codegen", "runtime", "backtest"],
                "status": "DONE_VERIFIED",
            }
        ):
            return False, case_count
    return True, case_count


def release_report(root: str | Path = ".") -> ReleaseReport:
    root_path = Path(root)
    missing_docs = tuple(path for path in REQUIRED_DOCS if not (root_path / path).exists())
    arch = architecture_report(root_path / "ast2python", max_lines=700)
    dup = duplicate_report(root_path / "ast2python")
    dist = distribution_manifest(root_path)
    cross_layer_catalog_ok, cross_layer_case_count = _cross_layer_catalog_status(root_path)
    manifest_file = f"RELEASE_MANIFEST_v{__version__}.json"
    manifest_exists = (root_path / manifest_file).exists()
    docs_ok = not missing_docs and manifest_exists
    ok = (
        docs_ok
        and arch.oversized_count == 0
        and dup.duplicate_group_count == 0
        and dist.hygiene_ok
        and cross_layer_catalog_ok
    )
    return ReleaseReport(
        version=__version__,
        ok=ok,
        docs_ok=docs_ok,
        missing_docs=missing_docs,
        architecture_ok=arch.oversized_count == 0,
        duplicate_ok=dup.duplicate_group_count == 0,
        distribution_ok=dist.hygiene_ok,
        cross_layer_catalog_ok=cross_layer_catalog_ok,
        cross_layer_case_count=cross_layer_case_count,
        manifest_file=manifest_file,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ast2python.release")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    report = release_report(args.root)
    payload = json.dumps(asdict(report), indent=2, sort_keys=True)
    if args.json:
        Path(args.json).write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover - exercised by module CLI smoke
    raise SystemExit(main())
