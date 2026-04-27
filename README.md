# AST2Python v0.1.0

AST2Python translates Pine AST JSON into readable Python modules that target runtime contract `1.4`.

v0.1.0 delivers:

- package `ast2python` version `0.1.0`
- defensive AST adapter for dict/JSON inputs
- diagnostics with stable contract and parity-risk codes
- deterministic naming and import management
- code emission with source comments and source map tracking
- real translation subset for declarations, literals, identifiers, expressions, var/reassign, `if`, `for ... to ...`, `request.security`, strategy declaration metadata, and runtime contract header
- JSON metadata, source map, and coverage artifacts
- CLI commands: `validate`, `translate`, `coverage`, `smoke`
- pytest, ruff, black, mypy, compileall gates

## CLI

```bash
ast2python validate tests/fixtures/ast/minimal_indicator.ast.json
ast2python translate tests/fixtures/ast/minimal_indicator.ast.json -o generated/
ast2python coverage tests/fixtures/ast/request_security.ast.json
ast2python smoke generated/minimal_indicator.py
```

## Runtime contract

Generated modules emit:

- `REQUIRED_RUNTIME_CONTRACT = "1.4"`
- runtime contract version check with `P2A_CONTRACT_VERSION_MISMATCH`
- explicit failures for unsupported nodes instead of silent placeholder translation

## Release archive

Build the reproducible release archive with:

```bash
./scripts/release_v0_1_0.sh
```
