# AST2Python v0.6.0

AST2Python translates Pine2AST JSON into readable, deterministic Python modules targeting PineLib runtime contract `1.4`.

v0.6.0 is the Pine2AST/PineLib pipeline-integration milestone. It keeps the v0.5.0 runtime-contract hardening and adds:

- direct CLI/API compatibility with current Pine2AST Program JSON and inspect-style envelopes containing `ast`/`program`
- integration fixtures copied from current Pine2AST golden AST output, plus generated Python snapshots
- generated module compile/import/run smoke against deterministic PineLib sample bars when PineLib is importable
- schema-level coverage reports with node-kind counts, unsupported-node catalog, and `schema_supported_ratio`
- release metadata and package docs updated for AST2Python `0.6.0` on runtime contract `1.4`

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
./scripts/release_v0_6_0.sh
```
