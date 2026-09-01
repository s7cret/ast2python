from __future__ import annotations

import argparse
import gzip
import io
import tarfile
from pathlib import Path

DETERMINISTIC_MTIME = 315532800  # 1980-01-01T00:00:00Z


def normalize_sdist(source: Path, output: Path) -> None:
    """Rewrite an existing source distribution with deterministic metadata.

    File bytes and archive member names come from the build backend output. Only
    transport metadata (member order, mtime, uid/gid, user/group names and gzip
    header fields) is normalized.
    """

    members: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(source, "r:gz") as archive:
        for member in archive.getmembers():
            payload = archive.extractfile(member).read() if member.isfile() else None
            members.append((member, payload))

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for original, payload in sorted(members, key=lambda item: item[0].name):
            member = tarfile.TarInfo(original.name)
            member.type = original.type
            member.linkname = original.linkname
            member.mode = original.mode
            member.size = 0 if payload is None else len(payload)
            member.mtime = DETERMINISTIC_MTIME
            member.uid = 0
            member.gid = 0
            member.uname = ""
            member.gname = ""
            archive.addfile(member, None if payload is None else io.BytesIO(payload))

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            compressed.write(tar_buffer.getvalue())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="normalize-sdist")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    normalize_sdist(args.source, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
