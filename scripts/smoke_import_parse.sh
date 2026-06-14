#!/usr/bin/env bash
set -euo pipefail
PYTHON=${PYTHON:-python}
$PYTHON - <<'PY'
import json
from pathlib import Path
from ast2python.ast.schema import load_ast
from ast2python.translator import translate_ast

path = Path('tests/fixtures/pine2ast/current_basic_indicator.ast.json')
program = load_ast(path)
result = translate_ast(program, module_name='smoke_indicator')
compile(result.code, 'smoke_indicator.py', 'exec')
print(json.dumps({'ok': True, 'module': result.module_name, 'lines': len(result.code.splitlines())}))
PY
