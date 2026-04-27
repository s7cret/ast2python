# AST2Python v0.5.0

AST2Python translates Pine AST JSON into readable, deterministic Python modules targeting PineLib runtime contract `1.4`.

v0.5.0 is the runtime-integration and package-architecture hardening milestone. It keeps the v0.4.0 control-flow/functions/visual foundation and adds:

- generated classes now inherit `GeneratedIndicatorBase`, `GeneratedStrategyBase`, or `GeneratedLibraryBase` from `ast2python.runtime_contract.generated_base`
- package split scaffolding for `runtime_contract` and `emitters` compatibility modules, while preserving existing public imports
- strategy phase contract hardening: generated code creates orders through `StrategyContext`, attaches runtime, and does not fill orders, call `end_bar()`, or call `commit_current()`
- CLI smoke now compiles and, when PineLib is importable, imports the generated module and runs it against deterministic sample bars
- source-map coverage reporting for executable Pine fixture lines, with tests requiring `>=95%`
- reference type generation policy for array/map/matrix identity/copy/history: assignment preserves identity, explicit `*.copy()` is diagnosed, and unsupported reference history fails before runtime
- `request.security` capture-safety diagnostics for mutable/reference captures, with strict mode failure
- date helper lowering for `year/month/weekofyear/dayofmonth/dayofweek/hour/minute/second` through `runtime.timefunc`
- integration tests that use local `[local-home]/pinelib` when available and gracefully skip runtime execution when PineLib is unavailable

## CLI

```bash
ast2python validate tests/fixtures/ast/minimal_indicator.ast.json
ast2python translate tests/fixtures/ast/v0_2_foundation_indicator.ast.json -o generated/
ast2python coverage tests/fixtures/ast/request_security.ast.json
ast2python smoke generated/v0_2_foundation_indicator.py
```

`ast2python smoke` accepts optional `--bars path.json|path.csv`; without it, it uses two deterministic sample bars.

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
./scripts/release_v0_5_0.sh
```
