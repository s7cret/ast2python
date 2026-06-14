# OpenPine pipeline

AST2Python sits between Pine2AST and the PineLib/OpenPine runtime layers.

```text
Pine source
  -> pine2ast 4.0 parse --json
  -> pine.ast_contract.v1 AST JSON
  -> ast2python 4.0 translate
  -> PineLib-targeted Python module
  -> OpenPine runtime/backtest orchestration
```

`pine2ast inspect --json` is not the default generator input. It is a metadata/debug/optimizer sidecar. AST2Python lowers `Program` AST payloads, including common envelopes where the program is stored under `ast` or `program`.

## Visual policy in the pipeline

OpenPine can choose visual behavior by environment:

- live trading / paper execution: `--visual-policy drop`;
- backtest/debug notebooks: `--visual-policy record`;
- strict parity validation: `--visual-policy error`.

AST2Python consumes frontend diagnostics but can intentionally ignore visual-only frontend runtime diagnostics under `drop`/`record`, because visual output is not part of live trading execution.
