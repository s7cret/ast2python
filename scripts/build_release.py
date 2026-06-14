from __future__ import annotations

from pathlib import Path

from ast2python.distribution import build_zip
from ast2python.version import __version__

if __name__ == "__main__":
    output = Path("dist") / f"ast2python-{__version__}.zip"
    digest = build_zip(Path.cwd(), output)
    print(f"{output} sha256={digest}")
