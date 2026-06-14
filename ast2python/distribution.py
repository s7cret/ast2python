from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from ast2python.version import __version__

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "build",
    "dist",
    "htmlcov",
    ".release_gate_reports",
    ".idea",
    ".vscode",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log"}
EXCLUDED_NAMES = {".DS_Store", ".coverage"}


@dataclass(frozen=True)
class DistributionManifest:
    version: str
    file_count: int
    total_bytes: int
    archive_root: str
    hygiene_ok: bool
    violations: tuple[str, ...]


def _is_excluded(path: Path) -> bool:
    if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in path.parts):
        return True
    if path.name in EXCLUDED_NAMES:
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    if path.name.startswith("ast2python-") and path.suffix == ".zip":
        return True
    return False


def iter_distribution_files(root: str | Path) -> Iterable[Path]:
    root_path = Path(root)
    for path in sorted(root_path.rglob("*")):
        rel = path.relative_to(root_path)
        if _is_excluded(rel):
            continue
        if path.is_file():
            yield path


def distribution_manifest(
    root: str | Path, *, archive_root: str | None = None
) -> DistributionManifest:
    root_path = Path(root)
    files = list(iter_distribution_files(root_path))
    total = sum(path.stat().st_size for path in files)
    violations: list[str] = []
    for path in root_path.rglob("*"):
        rel = path.relative_to(root_path)
        if path.is_file() and _is_excluded(rel):
            continue
        if path.is_file() and any(part == "__pycache__" for part in rel.parts):
            violations.append(str(rel))
    return DistributionManifest(
        version=__version__,
        file_count=len(files),
        total_bytes=total,
        archive_root=archive_root or f"ast2python-{__version__}",
        hygiene_ok=not violations,
        violations=tuple(sorted(violations)),
    )


def build_zip(root: str | Path, output: str | Path, *, archive_root: str | None = None) -> str:
    root_path = Path(root)
    output_path = Path(output)
    arc_root = archive_root or f"ast2python-{__version__}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in iter_distribution_files(root_path):
            rel = path.relative_to(root_path).as_posix()
            info = zipfile.ZipInfo(f"{arc_root}/{rel}")
            info.date_time = (2026, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    return hashlib.sha256(output_path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ast2python.distribution")
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("--root", default=".")
    zip_parser = subparsers.add_parser("build-zip")
    zip_parser.add_argument("--root", default=".")
    zip_parser.add_argument("--output", required=True)
    zip_parser.add_argument("--archive-root")
    args = parser.parse_args(argv)
    if args.command == "manifest":
        manifest = distribution_manifest(args.root)
        print(json.dumps(asdict(manifest), indent=2, sort_keys=True))
        return 0 if manifest.hygiene_ok else 1
    if args.command == "build-zip":
        digest = build_zip(args.root, args.output, archive_root=args.archive_root)
        print(json.dumps({"output": args.output, "sha256": digest}, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
