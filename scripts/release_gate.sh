#!/usr/bin/env bash
set -euo pipefail
PYTHON=${PYTHON:-python}
REPORT_DIR=${REPORT_DIR:-/tmp/ast2python_release_gate_reports}
mkdir -p "$REPORT_DIR"

run() {
  echo "[release-gate] $*"
  "$@"
}

run_logged() {
  local name="$1"
  shift
  local log="$REPORT_DIR/${name}.log"
  echo "[release-gate] $* > $log"
  if "$@" >"$log" 2>&1; then
    tail -n 40 "$log"
  else
    echo "[release-gate] ${name} failed; last log lines:" >&2
    tail -n 120 "$log" >&2 || true
    return 1
  fi
}

run "$PYTHON" -m compileall -q ast2python tests
run "$PYTHON" -m ruff check .
run "$PYTHON" -m black --check . --workers 1
run "$PYTHON" -m mypy ast2python
run_logged coverage env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$PYTHON" -m pytest -q -p pytest_cov --cache-clear tests/unit tests/integration --cov=ast2python --cov-report=term
run "$PYTHON" -m ast2python.quality duplicates ast2python
run "$PYTHON" -m ast2python.quality architecture ast2python --max-lines 700
run "$PYTHON" -m ast2python.lowering_matrix.validate
run "$PYTHON" -m ast2python.distribution manifest --root .
run "$PYTHON" -m ast2python.release --root .
run env PYTHON="$PYTHON" bash scripts/smoke_import_parse.sh
run env PYTHON="$PYTHON" bash scripts/wheel_smoke.sh

echo "[release-gate] ok"
