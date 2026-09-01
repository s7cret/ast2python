from __future__ import annotations

import argparse
import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from ast2python.version import __version__

_DISTRIBUTION_SCHEMA = "ast2python.distribution_manifest.v1"
_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "evidence",
        "htmlcov",
        "venv",
    }
)
_EXCLUDED_NAMES = frozenset({".coverage", "coverage.json", "coverage.xml"})
_EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo", ".whl", ".zip"})
_REQUIRED_FILES = (
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "pyproject.toml",
    "ast2python/__init__.py",
    "ast2python/version.py",
)


@dataclass(frozen=True, slots=True)
class DistributionFinding:
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True, slots=True)
class DistributionManifest:
    root: str
    package_version: str
    files: tuple[str, ...]
    findings: tuple[DistributionFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": _DISTRIBUTION_SCHEMA,
            "ok": self.ok,
            "root": self.root,
            "package_version": self.package_version,
            "file_count": len(self.files),
            "files": list(self.files),
            "findings": [item.to_dict() for item in self.findings],
        }


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _excluded(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    if any(
        part in _EXCLUDED_PARTS or part.endswith((".egg-info", ".dist-info"))
        for part in relative.parts
    ):
        return True
    if path.name in _EXCLUDED_NAMES or path.suffix in _EXCLUDED_SUFFIXES:
        return True
    return path.name.endswith((".log", ".tmp"))


def iter_distribution_files(root: str | Path = ".") -> tuple[Path, ...]:
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        return ()
    return tuple(
        path
        for path in sorted(root_path.rglob("*"))
        if path.is_file() and not _excluded(root_path, path)
    )


def build_distribution_manifest(root: str | Path = ".") -> DistributionManifest:
    root_path = Path(root).resolve()
    files = iter_distribution_files(root_path)
    relative_files = tuple(_relative(root_path, path) for path in files)
    selected = set(relative_files)
    findings: list[DistributionFinding] = []
    if not root_path.is_dir():
        findings.append(
            DistributionFinding(
                "missing_root", str(root_path), "distribution root is not a directory"
            )
        )
    for required in _REQUIRED_FILES:
        if required not in selected:
            findings.append(
                DistributionFinding(
                    "missing_required_file", required, "required release file is absent"
                )
            )
    for relative in relative_files:
        if relative.startswith("tests/fixtures/consumer/"):
            continue
        if relative.startswith("evidence/") and relative.endswith(".json"):
            continue
        if "__pycache__" in relative or relative.endswith((".pyc", ".pyo")):
            findings.append(
                DistributionFinding("selected_cache_artifact", relative, "cache artifact selected")
            )
    return DistributionManifest(
        root=str(root_path),
        package_version=__version__,
        files=relative_files,
        findings=tuple(findings),
    )


def _zip_info(name: str, mode: int) -> ZipInfo:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = (mode & 0xFFFF) << 16
    return info


def create_source_zip(
    root: str | Path,
    output: str | Path,
    *,
    root_name: str | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    manifest = build_distribution_manifest(root_path)
    if not manifest.ok:
        raise ValueError("distribution manifest is not clean")
    output_path = Path(output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    archive_root = root_name or f"ast2python-{__version__}"
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
        for relative in manifest.files:
            source = root_path / relative
            mode = stat.S_IMODE(source.stat().st_mode) or 0o644
            archive.writestr(_zip_info(f"{archive_root}/{relative}", mode), source.read_bytes())
    return {
        "schema_id": "ast2python.source_zip.v1",
        "output": str(output_path),
        "package_version": __version__,
        "root_name": archive_root,
        "file_count": len(manifest.files),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ast2python.distribution")
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("--root", default=".")
    zip_parser = subparsers.add_parser("build-zip")
    zip_parser.add_argument("--root", default=".")
    zip_parser.add_argument("--output", required=True)
    zip_parser.add_argument("--root-name")
    args = parser.parse_args(argv)
    if args.command == "manifest":
        payload = build_distribution_manifest(args.root).to_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if payload["ok"] else 1
    payload = create_source_zip(args.root, args.output, root_name=args.root_name)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
