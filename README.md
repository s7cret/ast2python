# Ast2Python 5.0.0rc6 — Stage 4

Ast2Python is the strict lowering and deterministic Python-emission backend of OpenPine.
It does **not** parse Pine source or repeat Pine2AST binding/type semantics.

## Compiler pipeline

```text
pine2ast.consumer_bundle.v1
→ strict admission
→ immutable CompilationSession
→ typed LoweringPlan v1
→ exact Target Manifest admission
→ deterministic Python module
→ Source Map v2
→ openpine.generated_artifact.v3
```

The only production input is `pine2ast.consumer_bundle.v1 / 1.0.0` produced by
`pine2ast==5.0.0rc6`. Raw AST dictionaries, wrapper aliases, local binders, inferred
semantic profiles, compatibility flags, stubs and silent no-op lowering are not accepted.

## Public API

```python
from pathlib import Path
from ast2python import compile_consumer_bundle, write_compilation_result

result = compile_consumer_bundle(Path("strategy.consumer-bundle.json"))
write_compilation_result(result, "generated/")
```

## CLI

```bash
ast2python validate-bundle strategy.consumer-bundle.json
ast2python inspect-bundle strategy.consumer-bundle.json
ast2python compile-bundle strategy.consumer-bundle.json \
  --output generated/ --module-name generated_strategy
```

## Version support

The compiler consumes version-exact Pine v1–v6 facts from Pine2AST. Ast2Python never
selects or rewrites the Pine version. Lowering differences such as eager/lazy logic,
legacy/fractional division, conditional evaluation and loop-bound policy are selected by
version-exact recipes.

## Runtime boundary

The generated module is self-contained relative to compiler packages: it imports neither
`pine2ast` nor `ast2python`. Execution requires a runtime implementing the exact admitted
Target Manifest. The bundled target is a **reference ABI only** and is explicitly marked
`REFERENCE_ONLY_PENDING_PINELIB_RC6`; it is not evidence of PineLib RC6 acceptance.

## Current acceptance status

- Exact corrected Pine2AST RC6 bundles v1–v6: accepted.
- Compiler-owned admission, IR, emission, source-map and artifact gates: implemented.
- Exact PineLib RC6 Target Manifest: not available; release acceptance remains blocked.
- Python 3.13 local gates: available.
- Python 3.11/3.12 and hosted Ruff/Black/MyPy gates: required externally.
- Merge, tag, publication and deployment: not authorized.

See `docs/` for architecture, contracts, security, limitations and the RC5→RC6 migration.

## RC6 near-final pass 3

The third near-final pass hardens release evidence without changing component ownership.
It records two separate conclusions:

```text
local_candidate_ready   — exact local source, tests, build, install and provenance
overall_release_ready   — local pass plus hosted Python/tooling, exact RC5 differential,
                          and exact PineLib RC6 target acceptance
```

A syntax check performed by Python 3.13 with `feature_version=(3, 11)` is reported as
syntax evidence only. It is never reported as a Python 3.11 runtime test. Likewise,
missing Ruff, Black, MyPy, hosted CI, RC5 wheel bytes or PineLib target evidence remain
explicit blockers rather than synthetic passes.

Run the local pass:

```bash
python -m ast2python.hardening.pass3 --root . --evidence ./evidence/pass3
```

The workflow `.github/workflows/rc6-pass3.yml` requires exact wheel URLs and SHA-256
values and pins all third-party actions to full commit SHAs.
