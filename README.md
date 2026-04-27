# AST2Python v0.9.0

AST2Python translates Pine2AST JSON into readable, deterministic Python modules targeting PineLib runtime contract `1.4`.

v0.9.0 is the release-candidate hardening milestone. It keeps v0.8.0 pipeline parity and adds:

- explicit public API stability checks for `Translator`, `TranslationResult`, `translate_ast`, `__version__` and contract version
- semver and limitations documentation for final 1.0 readiness
- source-map/report audit tests covering metadata shape and coverage thresholds
- translation performance smoke for real Pine2AST fixtures
- release manifest validation for current archive/docs inputs
- mypy-clean type hints across package, tests and release builder

## CLI

```bash
ast2python validate tests/fixtures/pine2ast/current_basic_indicator.ast.json
ast2python translate tests/fixtures/pine2ast/current_basic_indicator.envelope.json -o generated/ --module-name current_basic_indicator
ast2python coverage tests/fixtures/pine2ast/current_basic_indicator.ast.json
ast2python smoke generated/current_basic_indicator.py
```

`ast2python smoke` accepts optional `--bars path.json|path.csv`; without it, it uses two deterministic sample bars. If `pinelib` is unavailable, smoke still compiles/import-checks where possible and reports runtime as `skipped`.

## Runtime contract

Generated modules emit:

- `REQUIRED_RUNTIME_CONTRACT = "1.4"`
- runtime contract version check with `P2A_CONTRACT_VERSION_MISMATCH`
- explicit diagnostics/failures for unsupported nodes/builtins instead of silent placeholder translation
- no direct generated calls to `commit_current()` or strategy fills; runtime/backtest loop owns commits and broker execution
- generated visual calls routed through `runtime.visual` recorder methods

## Release archive

Build the reproducible release archive with:

```bash
./scripts/release_v0_9_0.sh
```
