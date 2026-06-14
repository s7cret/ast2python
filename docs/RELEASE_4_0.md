# Release 4.0.0

## Summary

AST2Python 4.0.0 is the GitHub-ready release aligned with Pine2AST 4.0.0 and the `pine.ast_contract.v1` AST contract.

## Breaking changes

- The accepted AST contract id is now `pine.ast_contract.v1`.
- Legacy schema identifiers were removed from public documentation and package data.
- Dependencies now target the 4.0 OpenPine stack release line.

## Hardening notes

- `ruff`, `black`, and `mypy` are part of the release gate.
- `python -m ast2python` is supported through `ast2python.__main__`.
- Visual calls are controlled by `--visual-policy drop|record|error`; default `drop` keeps live generation unblocked by plot/debug output.
- Wheel smoke installs with `--no-deps` by default and has a separate `FULL_STACK_WHEEL_SMOKE=1` mode for sibling/published OpenPine dependencies.
- Coverage was raised from the earlier ~71% baseline to the 100% release threshold, with focused coverage on calls, expressions, statements, metadata inputs/requests, and type inference.

## Release checklist

```bash
bash scripts/release_gate.sh
python -m ast2python.distribution build-zip --root . --output ast2python-4.0.0.zip
```

Expanded gate:

```bash
python -m compileall -q ast2python tests
python -m ruff check .
python -m black --check . --workers 1
python -m mypy ast2python
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p pytest_cov --cache-clear tests/unit tests/integration --cov=ast2python --cov-report=term
python -m ast2python.quality duplicates ast2python
python -m ast2python.quality architecture ast2python --max-lines 700
python -m ast2python.lowering_matrix.validate
python -m ast2python.distribution manifest --root .
python -m ast2python.release --root .
bash scripts/smoke_import_parse.sh
bash scripts/wheel_smoke.sh
```

Run the cross-repo OpenPine smoke before tagging the umbrella project:

```text
pine2ast parse -> ast2python translate -> generated module import -> pinelib/backtest/openpine smoke
```
