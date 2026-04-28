# AST2Python v1.0.0

AST2Python translates Pine2AST JSON into readable, deterministic Python modules targeting PineLib runtime contract `1.4`.

v1.0.0 is the finalized runtime-contract `1.4` release. Stack train metadata: `pain-stack-pine-v6-2026.04-r1`, `pine_language_version=6`, `pine_docs_baseline=2026-04`, `runtime_contract=1.4` (see `RELEASE_STACK_MANIFEST_2026_04_R1.json`). This is a verified Pine v6 subset/oracle-snapshot target, not a full Pine v6 parity claim. The April 2026 language-relevant baseline delta is UDT collection sorting via `sort_field` for `array.sort`, `array.sort_indices`, and `matrix.sort`; Pine Editor word-wrap is non-runtime UX.

It keeps v0.9.0 release-candidate hardening and finalizes:

- final audit documentation and release notes
- explicit v1.0 limitations carried forward without hidden feature expansion
- validated reproducible archive manifest for `dist/ast2python_v1_0_0.zip`
- deterministic generated code, source-map and coverage artifact checks
- successful compileall, pytest, mypy and release-script gates

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
./scripts/release_v1_0_0.sh
```
