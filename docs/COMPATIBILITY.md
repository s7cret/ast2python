# Compatibility

## Public contracts

| Contract | Status |
|---|---|
| `pine.ast_contract.v1` | accepted input AST contract |
| `openpine.frontend.v1` | optional sidecar metadata from Pine2AST/OpenPine |
| PineLib runtime contract `1.4` | target runtime API |

Regenerate AST fixtures with Pine2AST 4.0 so envelopes use the current `pine.ast_contract.v1` identifier.

## Supported lowering areas

- indicators and strategies with validated declarations;
- variable declarations, reassignment, tuples and common expression forms;
- selected drawing, math, string, TA, request, strategy, array, matrix and map built-ins;
- live-safe visual no-op mode and optional debug visual recorder mode;
- deterministic source-map and generation coverage metadata;
- fail-closed handling for unsupported realtime/repaint-sensitive features.

## Visual calls

`plot`, `plotshape`, `plotchar`, `hline`, `fill`, `bgcolor`, and `barcolor` are controlled by the `visual_policy` compile option:

| Policy | Behavior |
|---|---|
| `drop` | default; no-op visuals, suitable for live trading/runtime execution |
| `record` | emits `plot_recorder` / `_visual_call` calls for tests and debugging |
| `error` | visual calls are forbidden and fail generation |

When `visual_policy` is `drop` or `record`, Pine2AST visual-only runtime diagnostics are downgraded to AST2Python warnings so visuals do not block otherwise lowerable strategies.

## Out of scope

- Pine parsing;
- TradingView broker emulator parity;
- market-data transport;
- realtime rollback simulation;
- complete runtime parity for every built-in overload.
