# Stage 2: exact historical builtin bindings

This wave extends compiler candidate `3051201`. It is bounded evidence for the
listed builtins, not a Stage 2 completion claim or blanket Pine parity claim.

## Original reproduction

[The unchanged 24-case receipt](stage2-builtin-binding-baseline.json)
records the initial `exp`, `round`, `rsi`, and `macd` probe in Pine versions 1–6.
Each source used the declared version, `study` before v5 / `indicator` after,
and historical global names before v5 / namespaced names after. The input closes
were `[1, 2, 3, 2, 4, 3]`.

- `exp(1)`, `round(-1.5)`, and `rsi(close,2)` lacked exact target bindings in
  v1–v4. RSI also lacked its modern conventional binding.
- Modern `math.exp(1)` and `ta.macd(close,2,3,2)` reached emission but failed
  `A2P_PINELIB_UNBOUND_PARAMETER`.
- Modern `math.round(-1.5)` returned `-2`, exposing the runtime tie rule.
- The initial v1/v2 MACD probe used an unavailable tuple declaration. Those two
  producer failures are preserved as probe limitations, not classified as
  missing MACD ABI mappings. The final suite separately executes a standalone
  MACD call in v1/v2 and checks all three tuple values from v3 onward.

The receipt's `details: null` fields reflect the initial logger reading the
wrong exception attribute; the exception class and diagnostic message are
unaltered. They do not imply absence of structured compiler diagnostics.

## Exact contract

PineLib owns the audited source signatures, version availability, ABI callables,
and parameter bindings. Its supplementary `historical_call_bindings` table
preserves the existing official modern row inventory. The compiler accepts only
explicit historical direct global function rows with exact producer overload IDs
and Pine versions 1–4. It does not manufacture overloads from old spellings.

Audited modern rows explicitly select `producer_call_forms: [NAMESPACE_FUNCTION]`;
historical rows select `[FUNCTION]`. This matters because the producer already
normalizes `exp` to `pine:function:math.exp`, while the old argument is `x` and
the modern argument is `number`. A common canonical symbol is insufficient to
merge their source argument maps. Conflicting projections remain errors.

The current supplement audits `exp`, `round`, `sqrt`, `pow`, `abs`, `ceil`,
`floor`, `rsi`, `macd`, `sma`, and `wma`. Historical round precision is a separate producer overload, available
only in v4; its one-argument form is available in v1–v4. Modern round supports
both overloads. Omitted precision returns an integer; explicit precision zero
returns a float. Legacy RSI conventional `#overload:0` remains distinct from
the ratio formula `#overload:1`; the latter is explicitly unsupported by this
runtime binding wave and must not execute the conventional RMA kernel.

Emission still rejects unbound ABI parameters, unknown source parameters,
missing exact call triples, unavailable versions, and conflicting manifests.
No ABI parameter inference or lowering fallback was introduced.

The public `ast2python.lowering.audit_pinelib_call_binding` helper exposes the
compiler's structural argument contract for capability reports. It checks
producer candidate names against consumed arguments and reflects the exact ABI
signature to distinguish optional defaults from missing required arguments.
It recognizes request expression/timeframe and method receiver injections.
It leaves metadata-dependent inputs, generic result type context, and missing
dynamic source signatures explicitly unverified. Exact delegated identities
retain host-owned handler validation. A clean structural audit does not claim
value, qualifier, lifecycle, or numerical conformance. Production emission
semantics are unchanged.

## Independent execution evidence

`test_builtin_binding_execution.py` uses elementary constants and rational
EMA/RMA/WMA recurrence values authored separately from the runtime. It checks
direct and UDF execution (UDF syntax begins at v2), distinct written callsites,
named arguments, `na`, return types, unsupported version/signature cases,
historical and realtime callbacks, deferred historical order-fill rollback,
and JSON checkpoint restore. `test_historical_target_bindings.py` exercises
malformed supplemental rows, malformed explicit call forms, collisions,
unbound parameters, and a removed historical table without fallback.

Examples of independent expected values:

- RSI length 2 over `[1,2,3,2,4,3]`: `[na,na,100,50,250/3,50]`, from two
  initial price differences and subsequent gain/loss RMA updates.
- SMA length 3 over `[1,2,4,8,16]`: `[na,na,7/3,14/3,28/3]`.
- WMA length 3 over the same input: `[na,na,17/6,17/3,34/3]`.
- Historical MACD lengths `(2,3,2)` over `[1,2,3,2,4,3]`, using SMA-seeded EMA:
  `(na,na,na)`, `(na,na,na)`, `(1/2,na,na)`, `(1/6,1/3,-1/6)`,
  `(7/18,10/27,1/54)`, `(7/54,17/81,-13/162)`.

## MACD initialization: unresolved modern oracle

The first newly authored MACD test draft assumed first-source EMA initialization
for every version. Its first tuple expectation was `(0,0,0)` and all four v3–v6
cases failed because the runtime returned `na` during initialization. That draft
was not accepted evidence: the independent historical reference explicitly uses
an SMA seed. The corrected v3/v4 test now checks the complete rational trace
above, including initialization, against that primary specification.

Modern v5/v6 EMA initialization remains **UNVERIFIED** in this wave. Third-party
copies disagree with the historical reference; the authoritative modern section
was not extracted successfully. No seed-policy runtime change was made from
those copies. The modern compiled MACD test instead starts with four zero bars,
which initializes fast, slow, and signal to zero under either disputed rule,
then checks every result for the independently derived nonconstant sequence.
The first four modern bars are deliberately outside that test's numeric claim.
Restore is checked across the complete execution, but is not evidence resolving
the initialization oracle. This narrow test must not be counted as full modern
EMA/MACD parity.

Primary references consulted:

- [Pine v5 migration: renamed functions and removed RSI overload](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/)
- [Official v4 reference: historical argument names and SMA-seeded EMA example](https://in.tradingview.com/pine-script-reference/v4/)
- [Official v3 reference: historical SMA-seeded EMA example](https://fr.tradingview.com/pine-script-reference/v3/)

The initial provisional named-argument test also used `pow(x,y)`. The official
v4 reference specifies `pow(base,exponent)`, so the test's input spelling was
corrected without changing its independent numeric expectations.

## Local verification receipt

Final integration used PineLib manifest
`sha256:739bcc3e7167e49ecbb1f37c76b4fdb4763fad724364ba9ab1cebc989e17d9aa`.

- Python 3.11: 126 passed, zero failures or skips, 50.165 seconds. This includes
  all 122 new tests and the four existing Stage 4 nonvacuous gate tests.
- Python 3.13: all 122 new tests passed, zero failures or skips, 43.233 seconds.
- Ruff and Black checks cover all six changed/new Python files; `git diff --check`
  passes. No tests were skipped or existing expected values weakened.

The new `float(na)` cases first exposed missing producer cast argument evidence,
then an unsupported runtime `float` binding. Both owners corrected their
contracts; the final six generated cases pass through the actual `float(x)` ABI.

An earlier full compiler run, taken during owner integration, recorded 761 passed
and 10 failed: six pre-fix `float` cases, one nonvacuous hardening gate, and three
Windows infrastructure failures (two Git subprocess access failures and one
symlink privilege failure). The six cast cases and all four nonvacuous gates
pass in the final stable run. The three infrastructure outcomes still require
the Linux acceptance run; the initial full run is not represented as green.

Strict mypy also follows existing compiler imports and reports 434 errors in
ten other modules, chiefly emission mixin typing and missing typed frontend
imports. This bounded change does not suppress those diagnostics or claim the
whole compiler is type-check clean. Local JUnit/log receipts are retained under
`.pytest_cache/builtin-wave-*`; the root acceptance pipeline owns the immutable
cross-component and Linux evidence.
