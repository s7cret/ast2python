#!/usr/bin/env bash
set -euo pipefail
PYTHON=${PYTHON:-python}
rm -rf dist
if "$PYTHON" -c 'import build' >/dev/null 2>&1; then
  "$PYTHON" -m build --wheel
else
  echo "python-build is unavailable; falling back to pip wheel --no-build-isolation" >&2
  "$PYTHON" -m pip wheel --no-deps --no-build-isolation -w dist .
fi
TMP_VENV=$(mktemp -d)
cleanup() { rm -rf "$TMP_VENV"; }
trap cleanup EXIT
"$PYTHON" -m venv "$TMP_VENV/venv"
VENV_PY="$TMP_VENV/venv/bin/python"
if [[ "${FULL_STACK_WHEEL_SMOKE:-0}" == "1" ]]; then
  for sibling in ../pinelib ../pine2ast; do
    if [[ -d "$sibling" ]]; then
      "$VENV_PY" -m pip install --quiet -e "$sibling"
    fi
  done
  "$VENV_PY" -m pip install --quiet dist/*.whl
else
  "$VENV_PY" -m pip install --quiet --no-deps dist/*.whl
fi
"$VENV_PY" - <<'PY'
import ast2python
from ast2python.cli.main import main
print(ast2python.__version__)
assert callable(main)
PY
