# Migration from RC5 to RC6

Removed production surfaces:

```text
translate_ast(raw_ast, ...)
Translator.translate_program(...)
local binder/signature tables
local type inference
allow_invalid_ast
allow_contract_mismatch
allow_external_library_stubs
allow_unsupported_request_stubs
allow_realtime_local_simulation
allow_implicit_version_rewrite
```

New flow:

1. Produce `pine2ast.consumer_bundle.v1` with exact Pine2AST RC6.
2. Validate or inspect the bundle.
3. Compile against an exact Target Manifest.
4. Store the Python module, LoweringPlan, Source Map and Generated Artifact together.

RC5 raw-AST callers require an explicit upstream migration; no compatibility wrapper is
provided because it would restore the semantic split-brain removed by RC6.
