# Compatibility and acceptance boundary

## Production input

Ast2Python `5.0.0rc6` accepts only a fully verified:

```text
pine2ast.consumer_bundle.v1 / 1.0.0
producer package: pine2ast 5.0.0rc6
Pine versions: 1, 2, 3, 4, 5, 6
```

The consumer bundle must contain one immutable Pine version context, the exact AST v2,
complete semantic facts, node index, symbol/overload identities, source spans and all
required content hashes. Missing argument bindings, unresolved calls or blocking
frontend diagnostics fail closed.

## Compiler output

Accepted bundles are lowered to:

```text
ast2python.lowering_plan.v1
openpine.source_map.v2
openpine.generated_artifact.v3
```

The generated module imports neither `pine2ast` nor `ast2python`. It declares its exact
Target Manifest hash, operation set and capability set and refuses a different runtime.

## Explicitly unsupported inputs and behaviors

The following are not compatibility modes and are not accepted:

- raw `Program` AST JSON;
- `pine.ast_contract.v1` or arbitrary `ast`/`program` wrappers;
- missing, malformed, unknown or future Pine versions;
- local re-binding, local type inference or nearest-version fallback;
- unresolved symbol/overload/parameter identities;
- unknown Target ABI operations or capabilities;
- request, library or visual stubs;
- silent no-op/`na` replacement;
- runnable output from analysis-only admission.

## Current release acceptance

The corrected Pine2AST RC6 vectors v1–v6 are accepted. The bundled Target Manifest is a
compiler reference ABI and is explicitly marked `REFERENCE_ONLY_PENDING_PINELIB_RC6`.
It does not substitute for an exact PineLib `5.0.0rc6` target manifest and wheel.
Consequently the compiler-owned implementation can pass while coordinated merge and
release remain blocked.
