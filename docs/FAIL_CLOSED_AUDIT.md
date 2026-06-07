# Production Fail-Closed Audit — `ast2python` v2.17.x

**Date:** 2026-06-07
**Status:** P0.8 from `TZ_PRODUCT_READINESS.md` — completed
**Profile:** `production` (default) vs `diagnostic`

This document audits which unsafe behaviors are blocked in the `production`
compile profile. Each entry cites the runtime guard, the diagnostic code (if
any), and the unit test that proves the block.

## What is blocked by default

| Unsafe behavior | Code path | Diagnostic | Test |
|---|---|---|---|
| Missing `contract` envelope | `translator._enforce_metadata_contract` | `P2A_CONTRACT_VERSION_MISMATCH` | `test_missing_and_mismatch_contract_rejected` |
| Wrong `runtime_contract` value | `translator._enforce_metadata_contract` | `P2A_CONTRACT_VERSION_MISMATCH` | `test_missing_and_mismatch_contract_rejected` |
| Embedded ERROR/FATAL diagnostics in producer envelope | `translator._enforce_embedded_diagnostics` | `P2A_FRONTEND_GATE_BLOCK` | `test_embedded_frontend_error_rejected_by_default` |
| `parser_gate != "pass"` | `translator._enforce_frontend_gates` | `P2A_FRONTEND_GATE_BLOCK` | `test_frontend_gates_blocked_in_production` |
| `semantic_gate != "pass"` | `translator._enforce_frontend_gates` | `P2A_FRONTEND_GATE_BLOCK` | `test_frontend_gates_blocked_in_production` |
| `calc_on_every_tick` in strategy declaration | `translator._enforce_realtime_boundary` | `CALC_ON_EVERY_TICK_UNSAFE` | `test_calc_on_every_tick_rejected` |
| `varip` storage | `translator._enforce_varip_boundary` | `VARIP_UNSAFE` | `test_varip_rejected` |
| Production profile override with `allow_*` flags | `profiles.CompileProfile` | `ValueError("production compile profile forbids unsafe overrides")` | `test_allow_overrides_rejected_in_production` |

## What requires `diagnostic` profile + explicit override

| Behavior | Override | Effect |
|---|---|---|
| Invalid AST (embedded ERRORs) | `allow_invalid_ast=True` | translation proceeds, `parity_safe=False`, `unsafe=True` in metadata |
| Contract mismatch | `allow_contract_mismatch=True` | translation proceeds, parity risks recorded |
| Unknown builtins | `allow_unsupported_builtins=True` | translation proceeds with stub |

All overrides are recorded in `result.metadata.parity_risks` and surface
`parity_safe=False` so consumers can refuse to execute the generated module.

## Tests

```bash
cd ast2python
python -m pytest tests/unit/test_tz_contract_fail_closed.py -v
```

Result: **16 passed, 0 failed** at v2.17.0.

## What is NOT blocked (and why)

- `runtime.error`, `log.error`, `log.info`, `log.warning` — pass-through
  (void return, no parse error in pine2ast). The corresponding runtime
  behavior is the `pinelib` runtime's responsibility; codegen emits the
  call and trusts the runtime to honour it.
- `request.economic` — left as `UNSUPPORTED` in the parity matrix. Requires
  external FRED/TradingView data feed; out of scope until a data layer
  is implemented.

## Manual verification

```bash
ast2python translate envelope.json --compile-profile production
# → exits non-zero with one of the diagnostics above
ast2python translate envelope.json --compile-profile diagnostic --allow-invalid-ast
# → exits zero, but `result.metadata.unsafe = True`
```
