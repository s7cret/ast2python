#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ast2python.lowering_matrix import (  # noqa: E402
    LoweringMatrixError,
    validate_source_map_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate AST2Python source-map contract")
    parser.add_argument("--contract", help="Contract JSON path; defaults to bundled contract")
    args = parser.parse_args()
    try:
        validate_source_map_contract(args.contract)
    except LoweringMatrixError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("OK source-map contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
