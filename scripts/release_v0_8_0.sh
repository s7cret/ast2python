#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m compileall ast2python tests scripts
pytest -q
mypy ast2python tests scripts/build_release.py
RELEASE_MANIFEST=RELEASE_MANIFEST_v0.8.0.json python scripts/build_release.py
sha256sum dist/ast2python_v0_8_0.zip
