from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "RELEASE_MANIFEST_v0.1.0.json"
FIXED_TIMESTAMP = (2026, 4, 27, 0, 0, 0)


def iter_files() -> list[Path]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files: list[Path] = []
    for entry in manifest["include"]:
        path = ROOT / entry
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob("*") if item.is_file()))
        elif path.is_file():
            files.append(path)
    archive = ROOT / manifest["archive"]
    archive.parent.mkdir(parents=True, exist_ok=True)
    return sorted(set(files))


def write_archive() -> Path:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    archive = ROOT / manifest["archive"]
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
