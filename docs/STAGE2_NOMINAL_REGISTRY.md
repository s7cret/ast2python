# Stage 2 nominal registry admission and emission

This compiler wave emits the nominal declarations already present in the checked
lowering plan as `NOMINAL_TYPE_REGISTRY`. The literal is sealed by the existing
`emitted_module_hash`; generated-artifact v3 gains no fields. This is declaration
evidence, not a TradingView parity claim or full Stage 2 acceptance.

The module lists every checked type declaration, including unused declarations,
unused enum members, forward/cyclic fields, and private types retained by the
locked library projection. It does not reconstruct library declarations excluded
from the linked source. IDs keep the existing source hash, declaration name, and
source node identity. Type rows are sorted by ID; member and field order stays in
source order. Missing enum titles use the member name; an explicit empty title
stays empty. Constructor defaults remain ordinary expression lowering.

The exact additional PineLib manifest contract is:

```json
{
  "compiled_nominal_registry": {
    "revision": 1,
    "schema_id": "pinelib.nominal_registry.v1",
    "identity": "source-declaration",
    "admission": "module-literal-before-execution",
    "min_pine_version": 5
  }
}
```

Only that exact JSON contract adds `compiler.nominal_registry.v1` to the compiler
target. A boolean revision, floating-point version, missing field, or extra field
cannot satisfy it. Nominal plans require this capability as well as the existing
`compiler.nominal_types.v1` contract.

`ast2python.artifacts.admitted_nominal_registry(namespace, envelope,
admit_registry=NominalTypeRegistry.from_json)` returns the exact immutable runtime
owner. The host imports that owner and supplies its factory explicitly; the
compiler has no runtime import or registry implementation. The caller must
verify module bytes against the envelope before executing the module and calling
this helper, and must pass the returned owner to the session before callbacks or
checkpoint restore. The helper revalidates the complete envelope and delegates
registry shape, source/version identity, closure, and membership validation to
PineLib. A namespace alone cannot authenticate its originating module bytes.

`admit_registry` is a required keyword argument conforming to the generic
`NominalRegistryAdmission` protocol. The factory receives the module literal and
the exact `pine_version` and `expected_source_hash` from the verified envelope.
It is invoked once after all compiler admission checks, and its object and
validation exceptions pass through unchanged. It is never selected from the
generated namespace. Legacy absence still requires a callable factory argument
but does not invoke it.

Legacy nonnominal modules with neither nominal capability nor literal return
`None`. Pine v1-v4 cannot request this registry profile, even with an empty type
list. Nominal artifacts without the registry capability or literal require
recompilation; declarations are never learned from executed values.

## Test setup migration

The existing `runtime_for` fixture in `test_locked_library_execution.py` and
`run_source` fixture in `test_rc6_input_metadata.py` now verify the generated
artifact and pass its admitted registry into `RuntimeSession`. All 48 node IDs
and semantic expectations in `test_nominal_language_execution.py` and
`test_nominal_library_execution.py` are unchanged. Existing historical, realtime,
field rollback, shallow copy, method, enum, library, and JSON restore cases now
exercise the registry contract through those shared fixtures.

The earlier isolated admission suite retains all 61 node IDs. Its two tests of
pre-registry nominal output read artifacts captured before emission was changed:
`tests/fixtures/nominal_registry_legacy_v5.json` and the corresponding v6 file.
They verify the original source/module hashes and envelope, then retain the same
recompilation rejection expectation. Recompiling their source with the new emitter
would no longer test the legacy artifact. This migration is separate from changes
to runtime behavior or semantic expected results.

## Verification receipt

The initial new emission/target matrix had **15 failures and 6 passes** before
wiring. The integrated matrix has **130 passes**: 61 admission tests, 21 new
emission/target tests, and the unchanged 48 nominal/library tests.

The broader affected regression set passed on both interpreters:

| Interpreter | Result | Duration |
| --- | --- | --- |
| Python 3.11 | 569 passed, 0 failed, 0 skipped | 179.50 s |
| Python 3.13 | 569 passed, 0 failed, 0 skipped | 173.50 s |

That set includes scalar execution, references, intrabar collections, input
metadata, compiled requests, locked libraries, the complete previous builtin
test additions, and the nonvacuous gates. It uses PineLib manifest
`sha256:9226ba7a8404465ec416dd6f25bb92294083427a548761b678679b811648c546`.
Ruff passes on every changed Python file; Black passes on the new modules/tests
and nominal emission module.

Workspace receipts are `.runtime/evidence/nominal-registry-emission-before.*`,
`nominal-registry-compiled-first.*`, `nominal-registry-regression-py311.*`,
`nominal-registry-regression-py313.*`, and
`nominal-registry-test-migration.json`. This is an affected regression result,
not a claim that the complete compiler or host suite ran locally.

Recursive varip collection acceptance is unchanged. Existing request dependency
slicing restrictions are also unchanged: forwarding a registry to a request child
does not add support for UDF or UDT constructor dependencies in request source.

## Architecture correction after registry CI

The immutable registry CI run `34163246799` completed the test steps but rejected
two direct PineLib imports in this compiler's admission helper, including its
type-checking import. The existing architecture policy permits the compiler's
frontend dependency and reserves runtime construction for the host. This
correction follows that policy through explicit factory injection. It does not
change the policy, hide an import dynamically, or duplicate registry validation.

Relative to compiler `e0829d7881024abb8bb1882bafa0dad009068bb2`, the functional
change is confined to `ast2python/artifacts/nominal_registry.py`. Four existing
test fixture/registry files explicitly pass `NominalTypeRegistry.from_json` at
their 17 admission calls. Their original node IDs and expected assertions remain;
the 61 admission cases still exercise the real immutable owner and its negative
validation. Scalar availability files and their separate test corrections are
not part of this architecture correction.

The 25 new dependency-boundary tests failed before the change and pass after it.
They check required/invalid factories, exact argument forwarding and owner
identity, no invocation on legacy absence or failed compiler checks, unmodified
owner errors, and absence of static or dynamic runtime imports in the helper.
Together with the existing 61 admission, 21 emission and 48 nominal/library
cases, **155 tests pass on each Python 3.11 and 3.13**. Ruff passes and scoped mypy
validation of the helper passes. The unchanged full architecture checker also
passes locally: the compiler has only the allowed frontend edge. Local evidence
is recorded separately in `nominal-registry-dependency-*.json` and test logs;
this is not a replacement for the next immutable Linux CI run.
