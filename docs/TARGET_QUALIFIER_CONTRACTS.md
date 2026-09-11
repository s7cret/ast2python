# Exact target qualifier contracts — Stage 2, 2026-09-11

## Scope

Normalize the existing raw PineLib qualifier ceilings into the compiler-owned
exact target and enforce them at lowering and emission. Inference and source-free
bundle semantic verification remain producer-owned; this does not add a second
Pine analyzer or runtime implementation.

The normative ordering is `const < input < simple < series`. A supplied argument
must fit **both** the admitted source ceiling and the exact target ceiling. No
series-to-simple conversion, global qualifier default, or legacy-source backport
is performed. All operands of a variadic group are checked individually.

## Versioning and compatibility

The raw manifest remains `pinelib.target_manifest.v2`, schema version 2.0.0.
The normalized target is now `ast2python.target_manifest.v2`, schema version 2.0.0.
Every exact call binding has an immutable `parameter_qualifiers` mapping covering
exactly its declared parameters. The mapping is included in serialization and
content identity. Unknown, missing, duplicate and non-string declarations fail,
including manifests whose checksums were recomputed after removing these fields.

The unchanged reference-only v1 target remains loadable. An old v1 normalized
manifest cannot claim `EXACT_PINELIB_TARGET_MANIFEST_V2`: regenerate it from the
matching raw manifest. The `V2` in that acceptance label names the *raw* ABI.
Update the coordinated compiler/runtime/host/worker set and recompile artifacts;
matching package-version strings do not establish semantic or checkpoint identity.

## Two different guarantees

`validate_call_qualifiers` checks actual supplied arguments. A historical producer
signature may allow a broader domain than the target, yet a particular constant
argument fits both. That valid call is not rejected merely because other arguments
permitted by that historical source signature would fail. A non-fitting actual
argument is rejected before generated code is returned.

`audit_pinelib_qualifier_binding` independently checks qualifier-domain inclusion
for a supplied complete producer signature. It can report a mismatch for the same
binding whose constant call succeeds. Missing source qualifier metadata is
UNVERIFIED, not an unconstrained or compatible signature. This is a qualifier-only
audit: type shape, overload structure, return policy, defaults, numeric behavior
and method receiver admission have their existing separate owners.

The established structural `audit_pinelib_call_binding` is unchanged. The host
reports qualifier-domain evidence separately from structural binding and oracle
status, so a bound callable is not mislabeled as a fully compatible Pine function.

## Historical roles, inputs and emission

The existing `REQUEST_TIMEFRAME_ARGUMENT` injection explicitly consumes `resolution`
in v1–v4 and `timeframe` later. This exact injection authorizes the corresponding
qualifier role mapping. No generic resolution/timeframe alias is introduced for
other callables. Producer catalogues and historical spelling remain unchanged.

Omitted defaults are callee-owned, not actual supplied arguments. Their existing
metadata/admission paths remain intact (notably legacy generic `input`). Input
emission is a special path, so it explicitly runs the same argument check before
calling the admitted input registry. Re-emission of a plan against a changed target
and inconsistent qualifier evidence in a rehashed plan are regression-tested.
This is not authentication of arbitrary attacker-authored IR that lies consistently
about every fact; admission must still use trusted producer identities and the
existing bundle verifier.

## Tests and limitations

The added tests cover the independently specified four-element ordering, malformed
manifests, direct source-free compilation, named/positional/variadic arguments,
constant/input/simple values, historical request roles, input emission and schema
roundtrips. They do not certify all versioned signatures or TradingView numerics.
No independent TradingView execution and no whole-backtest speedup are claimed.

Official semantic reference:
https://www.tradingview.com/pine-script-docs/language/type-system/#qualifiers
