#!/usr/bin/env bash
set -euo pipefail

PYTHON=${PYTHON:-python}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TMP_ROOT=$(mktemp -d)
cleanup() { rm -rf "$TMP_ROOT"; }
trap cleanup EXIT

"$PYTHON" -m build --wheel --outdir "$TMP_ROOT/dist" "$ROOT"
shopt -s nullglob
WHEELS=("$TMP_ROOT"/dist/*.whl)
shopt -u nullglob
if [[ ${#WHEELS[@]} -ne 1 ]]; then
  echo "expected exactly one wheel, found ${#WHEELS[@]}" >&2
  exit 1
fi

"$PYTHON" -m venv "$TMP_ROOT/venv"
VENV_PY="$TMP_ROOT/venv/bin/python"
if [[ "${FULL_STACK_WHEEL_SMOKE:-0}" == "1" ]]; then
  for sibling in "$ROOT/../pinelib" "$ROOT/../pine2ast"; do
    if [[ -d "$sibling" ]]; then
      "$VENV_PY" -m pip install --quiet -e "$sibling"
    fi
  done
  "$VENV_PY" -m pip install --quiet "${WHEELS[0]}"
else
  "$VENV_PY" -m pip install --quiet --no-deps "${WHEELS[0]}"
fi

(
  cd "$TMP_ROOT"
  "$VENV_PY" -I - <<'PY'
from pathlib import Path
import sysconfig

import ast2python
from ast2python.cli.main import main

module_path = Path(ast2python.__file__).resolve()
purelib = Path(sysconfig.get_paths()["purelib"]).resolve()
assert module_path.is_relative_to(purelib), (module_path, purelib)
assert callable(main)
print(ast2python.__version__, module_path)
PY
)
