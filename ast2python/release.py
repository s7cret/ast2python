from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

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


def _cross_layer_catalog_status(root_path: Path) -> tuple[bool, int]:
    catalog_path = root_path / "ast2python/lowering_matrix/cross_layer_catalog.json"
    if not catalog_path.exists():
        return False, 0
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        case_count = int(catalog["case_count"])
        minimum = int(catalog["minimum_case_count"])
    except (OSError, KeyError, TypeError, ValueError):
        return False, 0
    return case_count >= minimum, case_count


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


if __name__ == "__main__":
    raise SystemExit(main())
