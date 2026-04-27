# AST2Python v0.7.0

AST2Python translates Pine2AST JSON into readable, deterministic Python modules targeting PineLib runtime contract `1.4`.

v0.7.0 is the target-strategy readiness/recovery milestone. It keeps v0.6.0 pipeline compatibility and adds:

- broader Pine2AST golden-fixture coverage for arrays, maps, matrices, imports, strategy exits, input.source and real-world strategy state
- deterministic lowering for array/map/matrix constructor APIs where PineLib supports reference objects
- import alias metadata plus external library call recorder diagnostics instead of silent runtime crashes
- P0 `strategy.*` order API lowering with diagnostics for non-P0 strategy APIs
- `alert`/`alertcondition` recorder generation and extended input metadata for source/time/session edges
- generated source-map/coverage thresholds enforced by integration tests

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
./scripts/release_v0_7_0.sh
```
