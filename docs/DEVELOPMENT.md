# Development

## Local checks

The local release gate mirrors CI and is intentionally strict:

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

or simply:

```bash
bash scripts/release_gate.sh
```

## AST input contract

Use `pine2ast parse --json` as AST2Python input. `pine2ast inspect --json` is a sidecar payload for debug/optimizer/OpenPine metadata and is not lowerable unless it also contains a `Program` node under `ast` or `program`.

## Visual policy

`--visual-policy drop` is the default and emits no-op visual statements for live/runtime usage. `--visual-policy record` enables `plot_recorder`/visual recorder output for tests and debugging. `--visual-policy error` turns visuals into hard generation errors.

## Wheel smoke

`bash scripts/wheel_smoke.sh` builds a wheel and installs it with `--no-deps` by default. This keeps CI independent from unpublished Git tags. Use `FULL_STACK_WHEEL_SMOKE=1` only in a full OpenPine checkout or after publishing `pinelib` and `pine2ast` tags.

## Architecture budget

New modules should stay under 700 physical lines unless there is a documented reason. Prefer focused helpers in `translator_parts/`, `translator_mixins/`, `binder_signatures/`, or `emitters/` over re-growing a monolith.
