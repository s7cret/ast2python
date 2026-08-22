#!/usr/bin/env bash
set -euo pipefail

PYTHON=${PYTHON:-python}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CONTRACTS_WHEEL=${OPENPINE_CONTRACTS_WHEEL:-}
PINE2AST_WHEEL=${OPENPINE_PINE2AST_WHEEL:-}
PINELIB_WHEEL=${OPENPINE_PINELIB_WHEEL:-}
PRODUCER_COMMITS=${OPENPINE_PRODUCER_COMMITS_JSON:-}
for value in "$CONTRACTS_WHEEL" "$PINE2AST_WHEEL" "$PINELIB_WHEEL"; do
  if [[ -z "$value" || ! -f "$value" ]]; then
    echo "exact local Contracts/Pine2AST/PineLib wheels are required" >&2
    exit 1
  fi
done
if [[ -z "$PRODUCER_COMMITS" ]]; then
  echo "OPENPINE_PRODUCER_COMMITS_JSON is required" >&2
  exit 1
fi
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
env -u PYTHONPATH "$VENV_PY" -m pip install --quiet \
  "$CONTRACTS_WHEEL" "$PINE2AST_WHEEL" "$PINELIB_WHEEL" "${WHEELS[0]}"

(
  cd "$TMP_ROOT"
  env -u PYTHONPATH OPENPINE_PRODUCER_COMMITS_JSON="$PRODUCER_COMMITS" \
    "$VENV_PY" -I - <<'PY'
from pathlib import Path
import sysconfig

import ast2python
from ast2python.artifact import build_generated_artifact_v2
from ast2python.cli.main import main
from openpine_contracts import validate_payload

module_path = Path(ast2python.__file__).resolve()
purelib = Path(sysconfig.get_paths()["purelib"]).resolve()
assert module_path.is_relative_to(purelib), (module_path, purelib)
assert callable(main)
artifact = build_generated_artifact_v2(
    source="wheel smoke\n",
    ast_payload={},
    emitted_module="class GeneratedIndicator:\n    pass\n",
    source_map=[],
)
validate_payload("openpine.generated_artifact.v2", artifact)
print(ast2python.__version__, module_path, artifact["content_hash"])
PY
)
