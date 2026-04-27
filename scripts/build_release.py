from __future__ import annotations

import json
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / os.environ.get("RELEASE_MANIFEST", "RELEASE_MANIFEST_v0.2.0.json")
FIXED_TIMESTAMP = (2026, 4, 27, 0, 0, 0)


def _is_releasable(path: Path) -> bool:
    ignored_parts = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist"}
    if any(part in ignored_parts for part in path.relative_to(ROOT).parts):
        return False
    return path.suffix not in {".pyc", ".pyo"}


def iter_files() -> list[Path]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files: list[Path] = []
    for entry in manifest["include"]:
        path = ROOT / entry
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob("*") if item.is_file() and _is_releasable(item)))
        elif path.is_file() and _is_releasable(path):
            files.append(path)
    archive = ROOT / str(manifest["archive"])
    archive.parent.mkdir(parents=True, exist_ok=True)
    return sorted(set(files))


def write_archive() -> Path:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    archive = ROOT / str(manifest["archive"])
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zf:
        for path in iter_files():
            relative = path.relative_to(ROOT).as_posix()
            info = ZipInfo(relative, date_time=FIXED_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    return archive


if __name__ == "__main__":
    print(write_archive())
