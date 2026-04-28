#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ast2python.lowering_matrix import LoweringMatrixError, validate_lowering_matrix  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate AST2Python lowering matrix")
    parser.add_argument("--matrix", help="Matrix JSON path; defaults to bundled matrix")
    args = parser.parse_args()
    try:
        validate_lowering_matrix(args.matrix)
    except LoweringMatrixError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("OK lowering matrix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
