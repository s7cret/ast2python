# Changelog

## 4.0.0

- Aligned generator input with `pine.ast_contract.v1` and the OpenPine 4.0 release line.
- Refactored translator implementation into focused `translator_parts`, `translator_mixins`, emitters, binder signatures and quality/release tooling.
- Added explicit visual policy: `drop` default for live-safe no-op visuals, `record` for debug/test plot recorder output, and `error` for strict visual rejection.
- Added `ast2python.__main__`, so `python -m ast2python ...` works beside the console script.
- Added Protocol-backed typing for translator mixins and brought `mypy ast2python` to a clean pass.
- Synchronized release gate with CI-style checks: `ruff`, `black`, `mypy`, hermetic pytest+coverage, quality, distribution, release, smoke and wheel smoke.
- Changed wheel smoke to install the built wheel with `--no-deps` by default; full-stack dependency validation is available through `FULL_STACK_WHEEL_SMOKE=1`.
- Raised coverage from the earlier ~71% baseline to the 100% release threshold, with focused coverage on calls, expressions, statements, metadata inputs/requests and type inference.
- Clarified docs: `pine2ast parse --json` is the lowering input; `pine2ast inspect --json` is a metadata/debug/optimizer sidecar unless it carries a `Program` AST.

## 0.x history

Earlier internal milestones established basic Pine2AST envelope validation, Python module emission, source-map metadata, PineLib runtime contract targeting, and initial OpenPine pipeline smoke tests.
