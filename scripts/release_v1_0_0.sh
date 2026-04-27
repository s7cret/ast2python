#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m compileall ast2python tests scripts
pytest -q
mypy ast2python tests scripts/build_release.py
RELEASE_MANIFEST=RELEASE_MANIFEST_v1.0.0.json python scripts/build_release.py
sha256sum dist/ast2python_v1_0_0.zip
