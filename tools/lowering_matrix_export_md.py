#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ast2python.lowering_matrix import (  # noqa: E402
    export_lowering_matrix_markdown,
    export_source_map_contract_markdown,
    validate_lowering_matrix,
    validate_source_map_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export AST2Python lowering docs")
    parser.add_argument("--matrix-output", default="docs/LOWERING_MATRIX.md")
    parser.add_argument("--source-map-output", default="docs/SOURCE_MAP_CONTRACT.md")
    args = parser.parse_args()
    validate_lowering_matrix()
    validate_source_map_contract()
    print(export_lowering_matrix_markdown(args.matrix_output))
    print(export_source_map_contract_markdown(args.source_map_output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
