# AST2Python v0.3.0

AST2Python translates Pine AST JSON into readable, deterministic Python modules targeting PineLib runtime contract `1.4`.

v0.3.0 is the type/declaration/request hardening milestone. It keeps the v0.2.0 expression foundation and adds:

- `TypeInfo` metadata with Pine qualifier lattice `const < input < simple < series`
- v6 bool validation for `na()`, `nz()`, and `fixnan()` before generated code can reach runtime
- explicit `P2A_UNKNOWN_OVERLOAD` diagnostics/failures for unsupported call overloads
- declaration metadata mapping for `strategy()`, `indicator()`, and `library()` P0/P1 fields with `P2A_UNSUPPORTED_DECLARATION_ARG`
- broader strategy context mapping for contract v1.4 settings
- `request.security()` callable generation hardening with request runtime context, capture-safe generated lambdas, stable state IDs, and nested-request diagnostics
- `time()` / `time_close()` generation through `runtime.timefunc` with named session/timezone argument preservation
- full input metadata emission, including source/session/timeframe defaults and UI fields
- generated runtime contract mismatch check against `REQUIRED_RUNTIME_CONTRACT = "1.4"`
- expanded source-map/coverage and compile tests for strategy declarations, inputs, time/session calls, bool validation, unknown overloads, nested requests, and request lambdas

## CLI

```bash
ast2python validate tests/fixtures/ast/minimal_indicator.ast.json
ast2python translate tests/fixtures/ast/v0_2_foundation_indicator.ast.json -o generated/
ast2python coverage tests/fixtures/ast/request_security.ast.json
ast2python smoke generated/v0_2_foundation_indicator.py
```

## Runtime contract

Generated modules emit:

- `REQUIRED_RUNTIME_CONTRACT = "1.4"`
- runtime contract version check with `P2A_CONTRACT_VERSION_MISMATCH`
- explicit diagnostics/failures for unsupported nodes/builtins instead of silent placeholder translation
- no direct generated calls to `commit_current()`; runtime owns bar commit

## Release archive

Build the reproducible release archive with:

```bash
./scripts/release_v0_3_0.sh
```
