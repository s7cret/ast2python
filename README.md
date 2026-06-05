# AST2Python

AST2Python translates Pine2AST JSON into readable, deterministic Python modules that run on PineLib.

## Scope

`ast2python` is the code-generation layer between Pine2AST JSON and PineLib. It owns deterministic lowering, generated runtime checks, source maps, coverage metadata, and explicit unsupported-feature diagnostics.

It does **not** parse Pine source, emulate TradingView bars/orders, fetch market data, run backtests, or optimize strategies.

## What It Supports

- Translation of Pine2AST indicator and strategy envelopes into Python modules.
- Generated code that targets PineLib runtime objects and helper namespaces.
- Runtime contract checks with clear `P2A_CONTRACT_VERSION_MISMATCH` diagnostics.
- Explicit diagnostics/failures for unsupported nodes and builtins instead of silent placeholder translation.
- Source-map and coverage metadata for generated modules.
- Visual call routing through PineLib's runtime visual recorder.
- Strategy intent generation without owning broker fills, equity, or execution authority.

## CLI

```bash
ast2python validate tests/fixtures/pine2ast/current_basic_indicator.ast.json
ast2python translate tests/fixtures/pine2ast/current_basic_indicator.envelope.json -o generated/ --module-name current_basic_indicator
ast2python coverage tests/fixtures/pine2ast/current_basic_indicator.ast.json
ast2python smoke generated/current_basic_indicator.py
```

`ast2python smoke` accepts optional `--bars path.json|path.csv`; without it, it uses two deterministic sample bars. If `pinelib` is unavailable, smoke still compiles/import-checks where possible and reports runtime as `skipped`.

## Runtime contract

Generated modules emit:

- `REQUIRED_RUNTIME_CONTRACT = "1.4"`
- runtime contract version check with `P2A_CONTRACT_VERSION_MISMATCH`
- explicit diagnostics/failures for unsupported nodes/builtins instead of silent placeholder translation
- no direct generated calls to `commit_current()` or strategy fills; the embedding runtime/caller loop owns commits and any broker execution
- generated visual calls routed through `runtime.visual` recorder methods

## License

MIT. See `LICENSE`.

## Installation, Docker, and Publication

```bash
./scripts/install.sh --dev
docker compose run --rm ast2python
```

## Acknowledgements

This project was developed with AI-assisted engineering workflows. The license and release obligations are defined only by `LICENSE` and the repository documentation above.

## Support / Donations

OpenPine development is independent and MIT-licensed. Donations are optional and help keep the public tooling maintained.

- Telegram: https://t.me/OpenPine
- TON: `UQAyIr2sQ4-_Q5L-4VINcU18khDas5GPbAlYEkQN6S_qzui2`
- SOL: `EbxMUK2W4RGeQZCTRFrdgpEJvnqtyczPZvBrQa1cYJnQ`

Support does not affect license terms, feature access, or project guarantees.
