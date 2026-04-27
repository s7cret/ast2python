# AST2Python v0.4.0

AST2Python translates Pine AST JSON into readable, deterministic Python modules targeting PineLib runtime contract `1.4`.

v0.4.0 is the control-flow/functions/reference/visual foundation milestone. It keeps the v0.3.0 type/declaration/request hardening and adds:

- statement and expression lowering for `if`/`switch`
- `for`/`while`/`break`/`continue`, with `while` max-iteration guard generation
- user function and method declarations with local scopes and Pine last-expression returns
- UDT dataclass and enum generation, including stable UDT history-member form `(obj[10]).field`
- visual recorder generation for `plot`, `plotshape`, object constructors (`label.new`, `line.new`, `box.new`, `table.new`) and visual `set_*`/`delete` methods
- visual object id storage in series/`var` fields and compile-time `P2A_VISUAL_OBJECT_USED_AS_VALUE` failures for arithmetic/bool misuse
- deterministic tuple discard names across scopes
- enriched source-map end-span fields and coverage generation ratio metadata
- v0.4 compile/snapshot tests for switch, loops, functions, methods, UDT history, enum, visual storage, and visual misuse diagnostics

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
- generated visual calls routed through `runtime.visual` recorder methods

## Release archive

Build the reproducible release archive with:

```bash
./scripts/release_v0_4_0.sh
```
