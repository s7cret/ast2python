# AST2Python v0.8.0

AST2Python translates Pine2AST JSON into readable, deterministic Python modules targeting PineLib runtime contract `1.4`.

v0.8.0 is the pipeline parity and runtime-integration hardening milestone. It keeps v0.7.0 target-strategy readiness and adds:

- multi-fixture `translate-many` CLI pipeline with deterministic per-module artifacts
- API/CLI snapshot parity checks against Pine2AST real-world fixtures
- PineLib v1.0 runtime import fallback and smoke execution compatibility
- stable metadata envelope checks for strategy/indicator/library generated modules
- explicit diagnostics surface for remaining unsupported runtime/schema nodes
- coverage docs for source-map, builtin and schema-threshold audit

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
./scripts/release_v0_8_0.sh
```
