# Architecture

## Ownership

Pine2AST owns parsing, version resolution, binding, types, qualifiers, overloads and
semantic-rule identities. Ast2Python consumes those facts and lowers them; it never
recomputes them. PineLib owns runtime operations and strategy intents. BacktestEngine
owns simulated fills and ledger state.

## Pipeline

```text
Consumer Bundle Admission
        ↓
AdmittedConsumerBundle (immutable)
        ↓
CompilationSession
        ↓
LoweringPlan v1 (typed, hash-bound, one IR node per source node)
        ↓
TargetManifest v1 admission
        ↓
Python Emitter + Source Map v2
        ↓
Generated Artifact v3
```

## Invariants

- one PineVersionContext from the producer;
- exact node→fact→IR traceability;
- exact symbol/overload identity for every resolved call;
- no nearest-version fallback;
- no raw AST production path;
- no local semantic binder;
- no stub/no-op/`na` replacement for unsupported behavior;
- target operation/capability subset checked before emission;
- deterministic output for identical bundle, target and module name;
- generated Python imports no compiler package.
