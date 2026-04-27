#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python -m compileall ast2python
pytest
if command -v ruff >/dev/null 2>&1; then
  ruff check .
else
  echo "ruff unavailable in environment; skipped"
fi
if command -v black >/dev/null 2>&1; then
  black --check .
else
  echo "black unavailable in environment; skipped"
fi
if command -v mypy >/dev/null 2>&1; then
  mypy
else
  echo "mypy unavailable in environment; skipped"
fi
python scripts/build_release.py
