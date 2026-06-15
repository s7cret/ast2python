# AST2Python 4.0.0

> Code-generation layer that lowers Pine2AST contracts into deterministic Python modules targeting the PineLib runtime.

[![Version](https://img.shields.io/badge/version-4.0.0-blue)](https://github.com/s7cret/ast2python) [![Python](https://img.shields.io/badge/python-%3E%3D3.11-blue)](https://github.com/s7cret/ast2python) [![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/s7cret/ast2python)


**GitHub description:** AST2Python converts Pine2AST JSON into PineLib-compatible Python modules with source maps, lowering diagnostics, visual-call policy, and OpenPine runtime metadata.

**Suggested topics:** `pine-script`, `code-generation`, `compiler-backend`, `tradingview`, `python`, `static-analysis`, `algorithmic-trading`, `openpine`.

## What AST2Python is

AST2Python is the compiler backend between `pine2ast` and `pinelib`. It receives a versioned Pine AST contract, validates the input envelope, lowers supported Pine constructs, and writes deterministic Python modules that can be executed by the PineLib/OpenPine runtime stack.

```text
Pine source -> pine2ast -> AST JSON -> ast2python -> generated Python -> pinelib/backtest-engine
```

## Contract alignment

| Component | Contract / version |
|---|---|
| Input AST | `pine.ast_contract.v1` |
| Optional frontend metadata | `openpine.frontend.v1` |
| Runtime target | PineLib runtime contract `1.4` |
| Supported Python | `>=3.11` |
| Release line | `4.0.0`, aligned with Pine2AST/PineLib 4.0.0 |

## What it does

- Validates Pine2AST parse JSON before lowering.
- Emits deterministic Python files for generated strategy/indicator modules.
- Preserves source-map and coverage metadata for debugging and CI.
- Maps supported Pine builtins into PineLib runtime calls.
- Applies an explicit policy for visual calls such as `plot`, `hline`, `fill`, `bgcolor`, and `barcolor`.
- Fails closed for unsupported parity-sensitive behavior unless an explicit compatibility flag is provided.
- Keeps OpenPine, PineLib, and backtest metadata available for downstream execution.

## What it does not do

AST2Python does not parse Pine source, fetch candles, simulate orders, calculate PnL, run optimizations, or provide a complete TradingView runtime. It is a code generator. Runtime behavior belongs to PineLib, Backtest Engine, MarketData Provider, and OpenPine.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Install from GitHub tag:

```bash
python -m pip install 'git+https://github.com/s7cret/ast2python.git@v4.0.0'
```

For source-stack development, install `pine2ast` and `pinelib` first:

```bash
python -m pip install -e ../pine2ast
python -m pip install -e ../pinelib
python -m pip install -e .
```

## CLI quick start

Generate AST JSON with Pine2AST, then lower it:

```bash
pine2ast parse strategy.pine --runtime-contract-v1-4 --json strategy.ast.json
ast2python validate strategy.ast.json
ast2python translate strategy.ast.json -o generated/ --module-name generated_strategy
```

Additional commands:

```bash
ast2python translate-many strategy_a.ast.json strategy_b.ast.json -o generated/
ast2python coverage strategy.ast.json
ast2python smoke generated/generated_strategy.py --bars fixtures/bars.json
ast2python lowering-matrix validate
ast2python lowering-matrix export-md docs/LOWERING_MATRIX.md
ast2python source-map-contract validate
ast2python source-map-contract export-md docs/SOURCE_MAP_CONTRACT.md
python -m ast2python translate strategy.ast.json -o generated/
```

## Visual-call policy

Visual calls are useful for tests and diagnostics but are not required for live execution. AST2Python makes the policy explicit:

```bash
# Default: live-safe no-op visual calls.
ast2python translate strategy.ast.json -o generated/ --visual-policy drop

# Debug/test mode: record visual output.
ast2python translate strategy.ast.json -o generated/ --visual-policy record

# Strict mode: reject visual calls during generation.
ast2python translate strategy.ast.json -o generated/ --visual-policy error
```

The default is `drop`, which keeps `plot()` and related calls from blocking runtime paths that do not need chart output.

## Compile profiles and safety flags

AST2Python is intentionally strict by default. Compatibility flags such as `--allow-invalid-ast`, `--allow-contract-mismatch`, `--allow-external-library-stubs`, and `--allow-unsupported-request-stubs` should be used only in controlled migration/test scenarios where the resulting behavior is explicitly reviewed.

## Repository layout

```text
ast2python/
  cli/                    command parser and command handlers
  emitters/               code-emission helpers
  lowering_matrix/        supported lowering matrix and validation tools
  runtime_contract/       target runtime interfaces and generated base
  templates/              generated-module templates
  translator.py           high-level lowering orchestration
  source_map.py           source-map metadata
  diagnostics.py          generator diagnostics
  profiles.py             compile profiles and policy knobs
```

## Release checks

```bash
python -m compileall -q ast2python tests
python -m ruff check .
python -m black --check . --workers 1
python -m mypy ast2python
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python -m ast2python.quality duplicates ast2python
python -m ast2python.quality architecture ast2python --max-lines 700
python -m ast2python.distribution manifest --root .
python -m ast2python.release --root .
bash scripts/wheel_smoke.sh
```

## Documentation

- `docs/ARCHITECTURE.md` — generator layers and ownership boundary.
- `docs/COMPATIBILITY.md` — public contracts, supported lowering areas, visual policy, non-goals.
- `docs/OPENPINE_PIPELINE.md` — how AST2Python fits into the OpenPine pipeline.
- `docs/DEVELOPMENT.md` — local checks and release workflow.
- `docs/RELEASE_4_0.md` — 4.0.0 release notes.
- `docs/SECURITY.md` — safe generation and integration guidance.

## License

MIT. See `LICENSE`.

## Support

OpenPine development is independent and MIT-licensed. Support is optional and does not change license terms, feature access, or project guarantees.

- Telegram: https://t.me/OpenPine
- TON: `UQAyIr2sQ4-_Q5L-4VINcU18khDas5GPbAlYEkQN6S_qzui2`
- SOL: `EbxMUK2W4RGeQZCTRFrdgpEJvnqtyczPZvBrQa1cYJnQ`