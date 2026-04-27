# AST2Python v0.2.0

AST2Python translates Pine AST JSON into readable, deterministic Python modules targeting PineLib runtime contract `1.4`.

v0.2.0 is the expression/variables/codegen foundation milestone. It keeps the v0.1.0 runtime-contract checks and adds:

- robust dict/JSON AST adapter fixtures for indicator and strategy snippets
- variable declaration, reassignment, scoped loop variables, and tuple declaration generation
- stable stateful TA/request `state_id` generation (`L{line}_C{col}_{func}_{ordinal}` with deterministic hash fallback)
- generated `request.security(..., lambda request_rt: ...)` expression callbacks
- history reference generation for built-in and generated series
- member access coverage for `ta`, `math`, `request`, `strategy`, `syminfo`, `timeframe`, `barstate`, `array`, `str`, and `color`
- inclusive Pine `for ... to ...` loops via `pine_range`
- source comments/source-map artifacts for generated statements
- enriched input metadata (`minval`, `maxval`, `step`, `options`, `group`, `inline`, `tooltip`, `display`, `active`, etc.)
- compile snapshots/tests for indicator and strategy fixtures

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
- explicit diagnostics/failures for unsupported nodes instead of silent placeholder translation
- no direct generated calls to `commit_current()`; runtime owns bar commit

## Release archive

Build the reproducible release archive with:

```bash
./scripts/release_v0_2_0.sh
```
